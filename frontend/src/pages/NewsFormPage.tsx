import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AppShell from "../components/AppShell";
import RichTextEditor from "../components/RichTextEditor";
import { api } from "../api/client";
import { newsApi } from "../api/news";
import { taskApi } from "../api/tasks";
import { messagingApi } from "../api/messaging";
import { attachmentApi } from "../api/attachments";
import type { Tag } from "../types/tasks";
import type { ThreadStatus } from "../types/messaging";
import CommentThreadStatusField from "../components/CommentThreadStatusField";
import "../styles/news.css";
import "../styles/form.css";

const fmtTime = (ts: number) => {
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
};

/** 表单快照（标题 / 摘要 / 正文）：自动保存差异判定与草稿比对的最小集合。 */
interface FormSnap {
  title: string;
  summary: string;
  content: string;
}

const snapJSON = (s: FormSnap) => JSON.stringify(s);

/** 旧版本地草稿（仅新建模式曾用）的读取键：一次性迁移后由服务端草稿接手。 */
const legacyDraftKey = () => "news-draft-new";

type SaveState = "idle" | "saving" | "saved" | "error";

export default function NewsFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = !!id;
  const fileRef = useRef<HTMLInputElement>(null);
  const newsIdRef = useRef<number | null>(id ? Number(id) : null);
  const autosaveTimer = useRef<number | null>(null);

  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [content, setContent] = useState("");
  // 封面「选完即传」：coverRef = 服务端引用（"" = 已标记清除，保存时同步）；coverDirty = 用户是否动过（决定保存时是否携带）
  const [coverRef, setCoverRef] = useState<string | null>(null);
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [coverUploading, setCoverUploading] = useState(false);
  const [coverDirty, setCoverDirty] = useState(false);
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [featured, setFeatured] = useState(false);
  const [isPublished, setIsPublished] = useState(true);
  const [commentThreadStatus, setCommentThreadStatus] = useState<ThreadStatus>("open");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(isEdit);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [savedAt, setSavedAt] = useState<number | null>(null);
  // 「已载入未发布的修改」（编辑模式：来自服务端草稿区）
  const [serverDraftLoaded, setServerDraftLoaded] = useState(false);
  // 「已恢复本地草稿」（仅新建模式，旧版 localStorage 草稿的一次性迁移）
  const [localRestored, setLocalRestored] = useState(false);
  // RichTextEditor 仅消费 content 作为初值；异步载入 / 草稿回退后需 remount 才能回填
  const [rteKey, setRteKey] = useState(0);

  // —— 自动保存用 refs（异步回调里读最新值，避免闭包过期）——
  const stateRef = useRef<FormSnap>({ title, summary, content });
  stateRef.current = { title, summary, content };
  const isPublishedRef = useRef(isPublished); isPublishedRef.current = isPublished;
  const savingRef = useRef(saving); savingRef.current = saving;
  const allowedRef = useRef(false); allowedRef.current = allowed === true;
  /** 载入时的「已发布版本」快照（放弃修改 = 回退到它）。 */
  const baseSnapRef = useRef<string | null>(null);
  /** 最近一次已写入服务端的表单快照（防重发 / 差异判定）。 */
  const lastSentRef = useRef<string | null>(null);
  /** 服务端是否已有草稿区内容（回退 / 放弃时需要 DELETE）。 */
  const hasServerDraftRef = useRef(false);
  /** 新建 → 首次自动保存时建档的并发去重。 */
  const ensureRowPromise = useRef<Promise<number> | null>(null);
  /** 自动保存串行队列：请求在途时再触发 → 排队重跑。 */
  const saveQueue = useRef({ inflight: false, dirty: false });
  /**
   * 用户是否已真实操作过表单（点击 / 输入 / 粘贴…）。
   * 编辑器挂载期会产生若干「非用户修改」的 HTML 变化（TrailingNode 追加尾段、
   * 序列化规范化等）——首次真实操作前一律按未修改处理：只同步基线，不触发自动保存。
   */
  const userDirtyRef = useRef(false);
  const markUserDirty = () => { userDirtyRef.current = true; };
  const runAutosaveRef = useRef<() => void>(() => {});
  const idleWaiters = useRef<Array<() => void>>([]);

  // 载入：新建模式尝试迁移旧版本地草稿；编辑模式拉取详情 + 服务端草稿区
  useEffect(() => {
    api.me()
      .then((d: any) => setAllowed(!!d.user?.permissions?.can_manage_news))
      .catch(() => setAllowed(false));
    taskApi.listTags().then((t: any) => setTags(t.results || t)).catch(() => {});

    if (!isEdit) {
      try {
        const raw = localStorage.getItem(legacyDraftKey());
        if (raw) {
          const snap = JSON.parse(raw);
          if (snap && (snap.title || snap.summary || snap.content)) {
            const restored: FormSnap = {
              title: snap.title || "",
              summary: snap.summary || "",
              content: snap.content || "",
            };
            setTitle(restored.title);
            setSummary(restored.summary);
            setContent(restored.content);
            setSavedAt(typeof snap.savedAt === "number" ? snap.savedAt : null);
            setLocalRestored(true);
            // 视为「已在本地保存」：用户真正改动后才触发服务端建档
            lastSentRef.current = snapJSON(restored);
            setRteKey((k) => k + 1);
          }
        }
      } catch { /* 旧草稿损坏则忽略，不阻断 */ }
      return;
    }

    const nid = Number(id);
    Promise.all([
      newsApi.get(nid),
      newsApi.getDraft(nid).catch(() => ({ draft: null })),
    ])
      .then(([n, dResp]) => {
        const draft = dResp?.draft ?? null;
        baseSnapRef.current = snapJSON({ title: n.title, summary: n.summary, content: n.content });
        if (draft) {
          // 已发布稿件的待发布修改：以草稿区为准继续编辑
          setTitle(draft.title);
          setSummary(draft.summary);
          setContent(draft.content);
          lastSentRef.current = snapJSON({ title: draft.title, summary: draft.summary, content: draft.content });
          hasServerDraftRef.current = true;
          setServerDraftLoaded(true);
          setSavedAt(draft.saved_at ? new Date(draft.saved_at).getTime() : null);
          setSaveState("saved");
        } else {
          // 未发布稿件：正文即草稿；已发布无草稿：正文为准
          setTitle(n.title);
          setSummary(n.summary);
          setContent(n.content);
          lastSentRef.current = snapJSON({ title: n.title, summary: n.summary, content: n.content });
        }
        setTagIds(n.tags.map((t) => t.id));
        setFeatured(n.featured);
        setIsPublished(n.is_published);
        setCoverRef(n.cover_image_url ?? null);
        setCoverPreview(n.cover_image_url);
        setCoverDirty(false);
        userDirtyRef.current = false;
        setRteKey((k) => k + 1);
        messagingApi.getThread({ news: n.id })
          .then((t) => setCommentThreadStatus(t.status))
          .catch(() => {});
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  /** 确保存在服务端行（新建模式首次自动保存 / 视频上传前建档）；并发去重。 */
  const ensureRow = (): Promise<number> => {
    if (newsIdRef.current) return Promise.resolve(newsIdRef.current);
    if (!ensureRowPromise.current) {
      const { title: t, summary: s, content: c } = stateRef.current;
      const fd = new FormData();
      fd.append("title", t.trim() || "未命名草稿");
      fd.append("summary", s);
      fd.append("content", c);
      fd.append("is_published", "false");
      const p = newsApi.create(fd).then((draft) => {
        newsIdRef.current = draft.id;
        // 旧版本地草稿已迁移到服务端 → 清掉，避免下次误恢复
        localStorage.removeItem(legacyDraftKey());
        setLocalRestored(false);
        return draft.id;
      });
      ensureRowPromise.current = p;
      p.then(
        () => { ensureRowPromise.current = null; },
        () => { ensureRowPromise.current = null; },
      );
    }
    return ensureRowPromise.current;
  };

  /** 单轮自动保存：差异判定 → 建档 / 写草稿 / 回退撤销。 */
  const autosaveOnce = async (): Promise<void> => {
    if (!allowedRef.current || savingRef.current || !userDirtyRef.current) return;
    const current = stateRef.current;
    const snapshot = snapJSON(current);
    if (snapshot === lastSentRef.current) return;

    const rowId = newsIdRef.current;

    // 新建且尚无行：内容达到“值得建档”的量才创建（避免空表单挂服务器）
    if (!rowId) {
      const text = current.content.replace(/<[^>]*>/g, "").trim();
      if (!current.title.trim() && !current.summary.trim() && text.length < 20) return;
      setSaveState("saving");
      try {
        await ensureRow();
        lastSentRef.current = snapshot;
        setSavedAt(Date.now());
        setSaveState("saved");
      } catch {
        setSaveState("error");
      }
      return;
    }

    // 已发布稿件回退到「已发布版本」：撤销草稿区（如有）
    if (isPublishedRef.current && snapshot === baseSnapRef.current) {
      if (hasServerDraftRef.current) {
        try {
          await newsApi.discardDraft(rowId);
          hasServerDraftRef.current = false;
          setServerDraftLoaded(false);
        } catch { /* 网络失败：留待下次自动保存再试 */ }
      }
      lastSentRef.current = snapshot;
      setSavedAt(null);
      setSaveState("idle");
      return;
    }

    setSaveState("saving");
    try {
      const resp = await newsApi.saveDraft(rowId, {
        ...(current.title.trim() ? { title: current.title } : {}),
        summary: current.summary,
        content: current.content,
      });
      lastSentRef.current = snapshot;
      if (resp.is_draft) hasServerDraftRef.current = true;
      setSavedAt(resp.saved_at ? new Date(resp.saved_at).getTime() : Date.now());
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  const runAutosave = () => {
    const q = saveQueue.current;
    if (q.inflight) { q.dirty = true; return; }
    q.inflight = true;
    autosaveOnce().finally(() => {
      q.inflight = false;
      if (q.dirty) {
        q.dirty = false;
        runAutosaveRef.current();
      } else {
        const waiters = idleWaiters.current;
        idleWaiters.current = [];
        waiters.forEach((w) => w());
      }
    });
  };
  runAutosaveRef.current = runAutosave;

  // 自动保存：防抖 1200ms（标题 / 摘要 / 正文变化触发；新建与编辑通用）
  useEffect(() => {
    if (loading) return;
    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    autosaveTimer.current = window.setTimeout(() => { runAutosaveRef.current(); }, 1200);
    return () => { if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, summary, content]);

  /**
   * 编辑器 onChange。首次真实操作之前，编辑器挂载期会自行产生若干非用户修改
   * （TrailingNode 追加尾段、HTML 序列化规范化等）——按「未修改」处理：
   * 仅同步基线，不触发自动保存，避免仅打开页面就产生草稿。
   */
  const handleEditorChange = (html: string) => {
    if (!userDirtyRef.current) {
      setContent(html);
      const patchSnap = (raw: string | null) => {
        if (!raw) return raw;
        try {
          const v = JSON.parse(raw);
          return snapJSON({ title: v.title ?? "", summary: v.summary ?? "", content: html });
        } catch { return raw; }
      };
      lastSentRef.current = patchSnap(lastSentRef.current);
      baseSnapRef.current = patchSnap(baseSnapRef.current);
      return;
    }
    setContent(html);
  };

  /**
   * 封面：选完即传（与正文插图同机制，避免把文件捆进保存请求）。
   * 成功只保留服务端引用；失败当场提示，不再拖到点「保存」时才暴露。
   */
  const onPickCover = async (f: File | null) => {
    if (!f) {
      // 「移除」：记录清除意图，保存时以空串同步（真正删除发生在服务端）
      setError("");
      setCoverRef("");
      setCoverPreview(null);
      setCoverDirty(true);
      return;
    }
    if (f.size > 5 * 1024 * 1024) {
      setError("封面图不能超过 5MB。");
      return;
    }
    setError("");
    setCoverUploading(true);
    try {
      const { url } = await newsApi.uploadCover(f);
      setCoverRef(url);
      setCoverPreview(url);
      setCoverDirty(true);
    } catch (e: any) {
      const reason = e?.message === "Failed to fetch"
        ? "请求没有发出去（网络问题）"
        : (e?.message || "未知错误");
      setError(`封面上传失败：${reason}。可重试，或先保存正文、稍后再补封面。`);
    } finally {
      setCoverUploading(false);
    }
  };

  const toggleTag = (tid: number) =>
    setTagIds((cur) => (cur.includes(tid) ? cur.filter((x) => x !== tid) : [...cur, tid]));

  /** 放弃修改（编辑模式）：清空服务端草稿区并回退到已发布版本。 */
  const discardServerDraft = async () => {
    const rowId = newsIdRef.current;
    if (!rowId) return;
    try {
      await newsApi.discardDraft(rowId);
    } catch (e: any) {
      setError(e?.message || "放弃修改失败，请重试");
      return;
    }
    let base: FormSnap = { title: "", summary: "", content: "" };
    try { base = { ...base, ...JSON.parse(baseSnapRef.current || "{}") }; } catch { /* 忽略 */ }
    const restored: FormSnap = { title: base.title || "", summary: base.summary || "", content: base.content || "" };
    setTitle(restored.title);
    setSummary(restored.summary);
    setContent(restored.content);
    setRteKey((k) => k + 1);
    userDirtyRef.current = false;
    lastSentRef.current = snapJSON(restored);
    hasServerDraftRef.current = false;
    setServerDraftLoaded(false);
    setSavedAt(null);
    setSaveState("idle");
    setError("");
  };

  /** 放弃旧版本地草稿（仅新建模式、尚未在服务端建档时出现）。 */
  const discardLocalDraft = () => {
    localStorage.removeItem(legacyDraftKey());
    setTitle(""); setSummary(""); setContent("");
    lastSentRef.current = snapJSON({ title: "", summary: "", content: "" });
    setSavedAt(null); setLocalRestored(false);
    userDirtyRef.current = false;
    setRteKey((k) => k + 1);
  };

  const uploadNewsVideo = async (file: File, onProgress: (ratio: number) => void): Promise<string> => {
    // 建档（新建且尚未保存时先存一份服务端草稿拿到 id；tus/Attachment 必须挂已存在的 news_id）
    const rowId = await ensureRow();
    const att = await attachmentApi.uploadRouted({
      parentType: "news", parentId: rowId, file, onProgress,
    });
    if (att && att.file_url) return att.file_url;
    // tus（>50MB）异步完成：回拉详情，取最新一条视频附件的 URL
    const fresh = await newsApi.get(rowId);
    const latest = (fresh.attachments || []).find((a) => a.file_type === "video");
    if (!latest) throw new Error("视频处理中，请稍后重试");
    return latest.file_url;
  };

  const submit = async () => {
    if (!title.trim()) { setError("请填写标题。"); return; }
    setSaving(true);
    setError("");
    try {
      // 收敛在途的自动保存 / 建档，避免与提交交叉（建档失败则回落为直接创建）
      if (ensureRowPromise.current) {
        try { newsIdRef.current = await ensureRowPromise.current; } catch { /* fallthrough */ }
      }
      if (saveQueue.current.inflight) {
        await new Promise<void>((resolve) => {
          idleWaiters.current.push(resolve);
          window.setTimeout(resolve, 5000);
        });
      }
      const fd = new FormData();
      fd.append("title", title.trim());
      fd.append("summary", summary);
      fd.append("content", content);
      fd.append("featured", String(featured));
      fd.append("is_published", String(isPublished));
      fd.append("comment_thread_status", commentThreadStatus);
      tagIds.forEach((tid) => fd.append("tag_ids", String(tid)));
      if (coverDirty) fd.append("cover_image_ref", coverRef ?? "");
      const saved = newsIdRef.current
        ? await newsApi.update(newsIdRef.current, fd)
        : await newsApi.create(fd);
      if (!newsIdRef.current) newsIdRef.current = saved.id;
      await messagingApi.applyHostThreadStatus({ news: saved.id }, commentThreadStatus);
      localStorage.removeItem(legacyDraftKey());
      navigate(`/news/${saved.id}`);
    } catch (e: any) {
      setError(e.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (allowed === null || loading) {
    return <AppShell><div className="container"><p className="news-empty">加载中…</p></div></AppShell>;
  }
  if (!allowed) {
    return (
      <AppShell>
        <div className="container" style={{ paddingTop: "var(--s-10)" }}>
          <div className="alert alert-warning">仅「信息组」成员可发布与编辑新闻。</div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/news"); }}>新闻</a>
            <span className="sep">/</span>
            <span>{isEdit ? "编辑" : "撰写"}</span>
          </nav>
          <h1>{isEdit ? "编辑新闻" : "撰写新闻"}</h1>
        </div>
      </div>

      <div className="container" style={{ paddingBottom: "var(--s-16)" }}>
        <div className="compose">
          {serverDraftLoaded && (
            <div className="alert alert-info compose-notice">
              <span>
                已载入一条未发布的修改{savedAt ? `（${fmtTime(savedAt)} 保存）` : ""}——点「保存修改」后公开页才会更新。
              </span>
              <button type="button" className="alert-link" onClick={discardServerDraft}>放弃修改</button>
            </div>
          )}
          {localRestored && (
            <div className="alert alert-info compose-notice">
              <span>已恢复本地草稿{savedAt ? `（${fmtTime(savedAt)}）` : ""}，重新编辑后会自动保存到服务器。</span>
              <button type="button" className="alert-link" onClick={discardLocalDraft}>放弃草稿</button>
            </div>
          )}
          {error && <div className="alert alert-danger">{error}</div>}

          {/* 标题：极简大号输入，写作优先 */}
          <input
            className="compose-title"
            value={title}
            onChange={(e) => { markUserDirty(); setTitle(e.target.value); }}
            placeholder="新闻标题…"
            maxLength={200}
            aria-label="标题"
          />

          {/* 元信息行：状态 / 封面 */}
          <div className="compose-meta">
            <div className="compose-pill">
              <span className="cp-label">状态</span>
              <div className="seg seg-sm" role="tablist" aria-label="发布状态">
                <button className="seg-btn" type="button" aria-selected={isPublished} onClick={() => setIsPublished(true)}>发布</button>
                <button className="seg-btn" type="button" aria-selected={!isPublished} onClick={() => setIsPublished(false)}>草稿</button>
              </div>
            </div>

            <div className="compose-pill">
              <span className="cp-label">封面</span>
              <button type="button" className="compose-cover" onClick={() => fileRef.current?.click()}
                      disabled={coverUploading}
                      title="上传封面图（≤5MB，建议横向；选完立即上传）">
                {coverUploading
                  ? <span className="cc-empty">上传中…</span>
                  : coverPreview
                    ? <img src={coverPreview} alt="封面" width={48} height={30} />
                    : <span className="cc-empty"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9.5" r="1.5" /><path d="M21 16l-5-5L5 20" /></svg>添加封面</span>}
              </button>
              {!coverUploading && (coverPreview || coverRef) && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onPickCover(null)}>移除</button>
              )}
            </div>
            <input ref={fileRef} type="file" accept="image/*" className="rte-file"
                   onChange={(e) => { const f = e.target.files?.[0] ?? null; e.target.value = ""; void onPickCover(f); }} />
          </div>

          {/* 大尺寸写作区 + 黏性工具栏（图片/链接/导入Word 集成在工具栏） */}
          <div
            onPointerDownCapture={markUserDirty}
            onKeyDownCapture={markUserDirty}
            onBeforeInputCapture={markUserDirty}
            onPasteCapture={markUserDirty}
            onDropCapture={markUserDirty}
          >
            <RichTextEditor
              key={rteKey}
              content={content}
              onChange={handleEditorChange}
              minHeight={560}
              imageUpload={(f) => newsApi.uploadImage(f).then((d) => d.url)}
              videoUpload={uploadNewsVideo}
              iframeEmbed
              wordImport
              placeholder="开始撰写正文，或从 Word 导入…"
            />
          </div>

          {/* 更多设置：摘要 / 标签 / 头条 */}
          <div className="compose-extras">
            <div className="field">
              <label className="label" htmlFor="nf-summary">摘要</label>
              <input id="nf-summary" className="input" value={summary} onChange={(e) => { markUserDirty(); setSummary(e.target.value); }}
                     placeholder="一句话摘要（列表 / 分享时展示，最多 280 字）" maxLength={280} />
            </div>

            <div className="field">
              <label className="label">标签</label>
              {tags.length === 0 ? (
                <p className="form-notice">暂无可选标签，标签由社长在任务模块维护。</p>
              ) : (
                <div className="tag-cloud" style={{ position: "static" }}>
                  {tags.map((t) => (
                    <button key={t.id} type="button" className="chip" aria-pressed={tagIds.includes(t.id)}
                            onClick={() => toggleTag(t.id)}>{t.name}</button>
                  ))}
                </div>
              )}
            </div>

            <label className="check">
              <input type="checkbox" checked={featured} onChange={(e) => setFeatured(e.target.checked)} />
              {" "}设为头条（列表页顶部展示）
            </label>

            <CommentThreadStatusField value={commentThreadStatus} onChange={setCommentThreadStatus} />
          </div>

          {/* 底部状态 + 操作 */}
          <div className="compose-foot">
            <div className="compose-stat">
              {saveState === "saving" && <span className="cs-saving">保存中…</span>}
              {saveState === "saved" && savedAt != null && (
                <span className="cs-saved">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
                  已保存到服务器 · {fmtTime(savedAt)}
                </span>
              )}
              {saveState === "error" && (
                <span className="cs-error">自动保存失败，请检查网络（修改暂未同步）</span>
              )}
              {saveState === "idle" && <span className="cs-hint">改动会自动保存到服务器</span>}
            </div>
            <div className="compose-actions">
              <button className="btn btn-ghost" type="button" onClick={() => navigate(-1)}>取消</button>
              <button className="btn btn-primary" type="button" onClick={submit} disabled={saving || coverUploading}>
                {saving ? "保存中…" : isEdit ? "保存修改" : isPublished ? "发布" : "保存草稿"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
