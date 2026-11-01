import { lazy, Suspense, useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { activityApi } from "../api/activities";
import { messagingApi } from "../api/messaging";
import { useSitePolicy } from "../api/sitePolicy";
import RichTextEditor from "../components/RichTextEditor";
import AppShell from "../components/AppShell";
import CommentThreadStatusField from "../components/CommentThreadStatusField";
import type { ActivityType, ExhibitionFormData, SurveyAudience, SurveyFormData } from "../types/activities";
import type { ThreadStatus } from "../types/messaging";
import { EMPTY_SURVEY_SCHEMA, countSurveyQuestions, summarizeSurveySchema, type SurveySchema } from "../utils/surveySchema";
import "../styles/form.css";

// 问卷设计器体积大（survey-creator-*），只在打开弹层时按需加载。
const SurveyDesignerModal = lazy(() => import("../components/SurveyDesignerModal"));

// 默认截止时间：当前 + N 天，格式 datetime-local 取值（yyyy-MM-ddThh:mm）
function defaultEnd(days: number): string {
  const d = new Date(Date.now() + days * 86400000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const t = new Date(local);
  return isNaN(t.getTime()) ? undefined : t.toISOString();
}

// ISO → datetime-local 取值（编辑模式回填）
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function ActivityFormPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const editId = id ? Number(id) : null;
  const policy = useSitePolicy();
  const syncMb = Math.round(policy.sync_upload_max_bytes / 1024 / 1024);
  const [type, setType] = useState<ActivityType>("deliberation");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [endAt, setEndAt] = useState(defaultEnd(3));
  const [permanent, setPermanent] = useState(false); // 长期有效：不设截止
  const [startAt, setStartAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [commentThreadStatus, setCommentThreadStatus] = useState<ThreadStatus>("open");

  // 众议字段
  const [options, setOptions] = useState<string[]>(["", ""]);
  const [k, setK] = useState(1);
  const [secret, setSecret] = useState(false);

  // 征集字段
  const [allowedExt, setAllowedExt] = useState(""); // 逗号分隔，空=不限
  const [maxSize, setMaxSize] = useState<string>(""); // MB，空=用站点同步上限
  const [maxFiles, setMaxFiles] = useState(5);
  const [maxSub, setMaxSub] = useState<string>(""); // 空=不限
  const [reviewEnabled, setReviewEnabled] = useState(true); // #51：复审可选，默认启用

  // 展示字段：是否启用投票（默认纯陈列，仅展品+赞/踩）
  const [votingEnabled, setVotingEnabled] = useState(false); // #56：展示投票可选，默认不启用

  // 调研字段：受众（创建后不可改）
  const [audience, setAudience] = useState<SurveyAudience>("members");
  // 调研问卷：发起前就能设计（随活动一起提交）；编辑态沿用后端 schema_editable 判断能否改。
  const [schema, setSchema] = useState<SurveySchema | null>(null);
  const [schemaDirty, setSchemaDirty] = useState(false);
  const [schemaEditable, setSchemaEditable] = useState(true);
  const [designerOpen, setDesignerOpen] = useState(false);
  // 新建时始终可设计；编辑时看后端生命周期判断（待开始 / 开放且零作答）。
  const surveyDesignEditable = !editId || schemaEditable;
  const surveyQuestionCount = countSurveyQuestions(schema ?? EMPTY_SURVEY_SCHEMA);

  const switchType = (t: ActivityType) => {
    setType(t);
    setEndAt(defaultEnd(t === "deliberation" ? 3 : 7));
  };

  // 受众选择（调研=作答资格；众议/展示=投票资格——公开时游客可投）。创建后不可改。
  const audienceField = (hint: string) => (
    <div className="field">
      <label className="label">受众{editId ? "（已固定）" : ""}</label>
      <div className="seg" role="radiogroup">
        <button type="button" className="seg-btn" aria-selected={audience === "members"} disabled={!!editId} onClick={() => !editId && setAudience("members")}>仅成员</button>
        <button type="button" className="seg-btn" aria-selected={audience === "public"} disabled={!!editId} onClick={() => !editId && setAudience("public")}>公开</button>
      </div>
      <div className="hint">{hint}</div>
    </div>
  );

  const setOption = (i: number, v: string) =>
    setOptions((opts) => opts.map((o, idx) => (idx === i ? v : o)));

  // 截止时间 + 「长期」复选框：长期活动不设截止，只有发起人/管理员能手动终结。
  const endAtField = (label: string) => (
    <div className="field">
      <label className="label">{label}</label>
      <input
        className="input"
        type="datetime-local"
        value={endAt}
        disabled={permanent}
        onChange={(e) => setEndAt(e.target.value)}
      />
      <label className="fb-attrib" style={{ marginTop: 8 }}>
        <input
          type="checkbox"
          checked={permanent}
          onChange={(e) => setPermanent(e.target.checked)}
        />
        <span>长期有效 —— 不设截止期限，直到发起人或管理员手动终结</span>
      </label>
    </div>
  );

  // 编辑模式：载入现有活动回填
  useEffect(() => {
    if (!editId) return;
    activityApi.get(editId).then((a) => {
      setType(a.type);
      setTitle(a.title);
      setBody(a.body);
      setStartAt(toLocalInput(a.start_at));
      setPermanent(!!a.is_permanent);
      setEndAt(toLocalInput(a.end_at) || defaultEnd(a.type === "deliberation" ? 3 : 7));
      if (a.type === "collection") {
        setAllowedExt(a.allowed_extensions || "");
        setMaxSize(a.max_file_size ? String(Math.round(a.max_file_size / 1024 / 1024)) : "");
        setMaxFiles(a.max_files_per_submission);
        setMaxSub(a.max_submissions != null ? String(a.max_submissions) : "");
        setReviewEnabled(a.review_enabled);
      } else if (a.type === "deliberation") {
        setOptions(a.options ? a.options.map((o) => o.text) : ["", ""]);
        setK(a.max_choices_per_voter);
        setSecret(a.is_secret_ballot);
        setAudience(a.audience || "members");
      } else if (a.type === "exhibition") {
        setVotingEnabled(a.voting_enabled);
        setK(a.max_choices_per_voter);
        setSecret(a.is_secret_ballot);
        setAudience(a.audience || "members");
      } else if (a.type === "survey") {
        setAudience(a.audience || "members");
        setSchema((a.schema as SurveySchema) || null);
        setSchemaEditable(!!a.schema_editable);
      }
      messagingApi.getThread({ activity: a.id })
        .then((t) => setCommentThreadStatus(t.status))
        .catch(() => {});
    }).catch((e: any) => setError(e?.message || "加载失败"));
  }, [editId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!title.trim()) {
      setError("请填写标题");
      return;
    }
    if (type === "deliberation") {
      const texts = options.map((o) => o.trim()).filter(Boolean);
      if (texts.length < 2) {
        setError("众议至少需要 2 个选项");
        return;
      }
      if (k < 1 || k > texts.length) {
        setError(`每人最多选几项须在 1..${texts.length} 之间`);
        return;
      }
    } else if (type === "collection") {
      if (maxFiles < 1) {
        setError("单作品文件数上限至少为 1");
        return;
      }
    }
    if (!permanent && !endAt) {
      setError("请选择截止时间，或勾选「长期有效」");
      return;
    }
    // 展示:创建/编辑只带标量(展品在详情页布展);K>=1 由后端序列化器把关

    setSubmitting(true);
    try {
      let saved: { id: number };
      if (type === "deliberation") {
        const payload = {
          type: "deliberation" as const,
          title: title.trim(),
          body,
          max_choices_per_voter: k,
          is_secret_ballot: secret,
          audience,
          start_at: toIso(startAt),
          end_at: permanent ? null : (toIso(endAt) ?? null),
          is_permanent: permanent,
          option_texts: options.map((o) => o.trim()).filter(Boolean),
          comment_thread_status: commentThreadStatus,
        };
        saved = editId
          ? await activityApi.update(editId, payload)
          : await activityApi.create(payload);
      } else if (type === "collection") {
        const payload = {
          type: "collection" as const,
          title: title.trim(),
          body,
          allowed_extensions: allowedExt.trim(),
          max_file_size: maxSize.trim() ? Math.round(parseFloat(maxSize) * 1024 * 1024) : null,
          max_files_per_submission: maxFiles,
          max_submissions: maxSub.trim() ? parseInt(maxSub, 10) : null,
          review_enabled: reviewEnabled,
          start_at: toIso(startAt),
          end_at: permanent ? null : (toIso(endAt) ?? null),
          is_permanent: permanent,
          comment_thread_status: commentThreadStatus,
        };
        saved = editId
          ? await activityApi.update(editId, payload as unknown as Record<string, unknown>)
          : await activityApi.create(payload);
      } else if (type === "exhibition") {
        // 展示创建/编辑:JSON 标量(展品改在详情页 add_exhibit)
        const payload: ExhibitionFormData = {
          type: "exhibition",
          title: title.trim(),
          body,
          voting_enabled: votingEnabled,
          max_choices_per_voter: k,
          is_secret_ballot: secret,
          audience,
          start_at: toIso(startAt),
          end_at: permanent ? null : (toIso(endAt) ?? null),
          is_permanent: permanent,
          comment_thread_status: commentThreadStatus,
        };
        saved = editId
          ? await activityApi.update(editId, payload as unknown as Record<string, unknown>)
          : await activityApi.create(payload);
      } else {
        const payload: SurveyFormData = {
          type: "survey",
          title: title.trim(),
          body,
          audience,
          start_at: toIso(startAt),
          end_at: permanent ? null : (toIso(endAt) ?? null),
          is_permanent: permanent,
          comment_thread_status: commentThreadStatus,
        };
        // 新建：设计过就随创建请求一起带上；编辑：只在设计稿有改动时带上
        // （避免与「问卷已锁定」的门禁硬撞）。
        if (schema && (!editId || schemaDirty)) payload.schema = schema;
        saved = editId
          ? await activityApi.update(editId, payload as unknown as Record<string, unknown>)
          : await activityApi.create(payload);
      }
      await messagingApi.applyHostThreadStatus({ activity: saved.id }, commentThreadStatus);
      navigate(`/activity/${saved.id}`);
    } catch (err: any) {
      setError(err.message || (editId ? "保存失败" : "创建失败"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/activity"); }}>互动</a>
            <span className="sep">/</span>
            <span>{editId ? "编辑互动" : "发起互动"}</span>
          </nav>
          <h1>{editId ? "编辑互动" : "发起互动"}</h1>
          <p className="section-sub">{editId ? "修改待开始互动的时间与内容（开放后即锁定）。" : "发起一场众议、征集、展示或调研。调研可在发起前直接把问卷设计好。"}</p>
        </div>
      </div>

      <div className="container" style={{ maxWidth: 820, paddingTop: "var(--s-8)", paddingBottom: "var(--s-16)" }}>
        {error && (
          <div className="alert alert-danger" style={{ margin: "var(--s-4) 0" }}>
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={submit} className="card card-pad">
          <div className="field">
            <label className="label">类型{editId ? "（已固定）" : ""}</label>
            <div className="seg" role="tablist" style={{ flexWrap: "wrap" }}>
              <button type="button" className="seg-btn" aria-selected={type === "deliberation"} disabled={!!editId} onClick={() => !editId && switchType("deliberation")}>众议（投票）</button>
              <button type="button" className="seg-btn" aria-selected={type === "collection"} disabled={!!editId} onClick={() => !editId && switchType("collection")}>征集（收作品）</button>
              <button type="button" className="seg-btn" aria-selected={type === "exhibition"} disabled={!!editId} onClick={() => !editId && switchType("exhibition")}>展示（陈列评分）</button>
              <button type="button" className="seg-btn" aria-selected={type === "survey"} disabled={!!editId} onClick={() => !editId && switchType("survey")}>调研（问卷）</button>
            </div>
          </div>

          <div className="field">
            <label className="label">标题 <span className="hint">*</span></label>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required placeholder="一句话说明" />
          </div>

          <div className="field">
            <label className="label">正文说明</label>
            <RichTextEditor
              content={body}
              onChange={setBody}
              minHeight={320}
              placeholder="背景、规则、要求……（支持图片 / iframe 嵌入）"
              imageUpload={(f) => activityApi.uploadImage(f).then((d) => d.url)}
              iframeEmbed
              wordImport
            />
          </div>

          <div className="field">
            <label className="label">开始时间 <span className="hint">（选填；不填则创建即开放，填未来时间则先「待开始」到点自动开放）</span></label>
            <input className="input" type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} />
          </div>

          {type === "deliberation" ? (
            <>
              <div className="field">
                <label className="label">投票选项 <span className="hint">（至少 2 个，开放即锁定）</span></label>
                {options.map((o, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                    <input className="input" value={o} onChange={(e) => setOption(i, e.target.value)} maxLength={200} placeholder={`选项 ${i + 1}`} />
                    {options.length > 2 && (
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOptions(options.filter((_, idx) => idx !== i))}>移除</button>
                    )}
                  </div>
                ))}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOptions([...options, ""])}>+ 增加选项</button>
              </div>

              <div className="form-grid">
                <div className="field">
                  <label className="label">每人最多选几项（K）</label>
                  <input className="input" type="number" min={1} value={k} onChange={(e) => setK(parseInt(e.target.value, 10) || 1)} />
                  <div className="hint">K=1 即一人一票；K&gt;1 即一人多票（最多选 K 项）。</div>
                </div>
                {endAtField("投票截止")}
              </div>

              <div className="field">
                <label className="fb-attrib">
                  <input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} />
                  <span>秘密投票 —— 仅聚合计数可见，个人投票明细仅超级管理员可见</span>
                </label>
              </div>
              {audienceField("公开：未登录访客也能投票（按设备防重复）；仅成员：须登录后投票。创建后不可改。")}
            </>
          ) : type === "collection" ? (
            <>
              <div className="form-grid">
                <div className="field">
                  <label className="label">允许后缀 <span className="hint">（逗号分隔，空=不限）</span></label>
                  <input className="input" value={allowedExt} onChange={(e) => setAllowedExt(e.target.value)} placeholder=".jpg,.png,.pdf" />
                </div>
                <div className="field">
                  <label className="label">单文件大小上限（MB） <span className="hint">（空={syncMb}MB）</span></label>
                  <input className="input" type="number" min={1} value={maxSize} onChange={(e) => setMaxSize(e.target.value)} placeholder="50" />
                </div>
              </div>
              <div className="form-grid">
                <div className="field">
                  <label className="label">单作品文件数上限</label>
                  <input className="input" type="number" min={1} value={maxFiles} onChange={(e) => setMaxFiles(parseInt(e.target.value, 10) || 1)} />
                </div>
                <div className="field">
                  <label className="label">最大征集数量 <span className="hint">（满额自动关闭；空=不限）</span></label>
                  <input className="input" type="number" min={1} value={maxSub} onChange={(e) => setMaxSub(e.target.value)} placeholder="不限" />
                </div>
              </div>
              {endAtField("收件截止")}
              <div className="field">
                <label className="fb-attrib">
                  <input type="checkbox" checked={reviewEnabled} onChange={(e) => setReviewEnabled(e.target.checked)} />
                  <span>需要复审 —— 勾选：收件后逐个录用/退稿，仅录用作品公开展示；不勾：作品提交即全部公开。</span>
                </label>
              </div>
            </>
          ) : type === "exhibition" ? (
            <>
              {/* 展示：截止 + 启用投票开关（展品在详情页布展） */}
              {endAtField("展示截止")}
              <div className="field">
                <label className="fb-attrib">
                  <input
                    type="checkbox"
                    checked={votingEnabled}
                    disabled={!!editId}
                    onChange={(e) => setVotingEnabled(e.target.checked)}
                  />
                  <span>
                    启用投票 —— 勾选：成员可对展品投票（1..K）；不勾：纯陈列，仅展品 + 赞/踩。展品在创建后于详情页录入。
                    {editId && <span className="hint">（投票开关创建后不可改）</span>}
                  </span>
                </label>
              </div>
              {votingEnabled && (
                <div className="form-grid">
                  <div className="field">
                    <label className="label">每人最多投几项（K）</label>
                    <input className="input" type="number" min={1} value={k} onChange={(e) => setK(parseInt(e.target.value, 10) || 1)} />
                    <div className="hint">对展品投票：K=1 一人一展品；K&gt;1 一人最多投 K 个展品。赞/踩另算，可随时改。</div>
                  </div>
                  <div className="field">
                    <label className="fb-attrib" style={{ marginTop: 28 }}>
                      <input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} />
                      <span>秘密投票</span>
                    </label>
                  </div>
                </div>
              )}
              {audienceField("公开：未登录访客可浏览，启用投票时也能直接投票（按设备防重复）；仅成员：须登录。创建后不可改。")}
            </>
          ) : (
            <>
              <div className="field">
                <label className="label">
                  问卷题目
                  <span className="hint">
                    （{surveyDesignEditable ? "发起前即可设计，之后仍可补题" : "已收到作答，问卷已锁定"}）
                  </span>
                </label>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={!surveyDesignEditable}
                    onClick={() => setDesignerOpen(true)}
                  >
                    {surveyQuestionCount > 0 ? "编辑问卷" : "设计问卷"}
                  </button>
                  <span className="hint">{summarizeSurveySchema(schema ?? EMPTY_SURVEY_SCHEMA)}</span>
                </div>
                {!surveyDesignEditable && (
                  <div className="alert alert-warning" style={{ marginTop: 8 }}>
                    <span>该问卷已收到作答，无法再修改题目；需要调整请结束本场调研后重新发起。</span>
                  </div>
                )}
                <div className="hint">
                  {editId
                    ? "在弹层里增删题目，点「完成」后回填本页，再点「保存修改」落库。"
                    : "在弹层里增删题目，点「完成」后回填本页，题目会随「发起互动」一起创建。"}
                </div>
              </div>
              {audienceField("公开：访客可列出、打开、提交；仅成员：须登录。创建后不可改。问卷题目可在本页设计。")}
              {endAtField("征答截止")}
            </>
          )}

          <CommentThreadStatusField value={commentThreadStatus} onChange={setCommentThreadStatus} />

          <div style={{ display: "flex", gap: 12, marginTop: "var(--s-4)" }}>
            <button className="btn btn-primary" type="submit" disabled={submitting}>{submitting ? "保存中…" : editId ? "保存修改" : "发起互动"}</button>
            <button className="btn btn-ghost" type="button" onClick={() => navigate("/activity")}>取消</button>
          </div>
        </form>

        {designerOpen && (
          <Suspense
            fallback={
              <div
                style={{
                  position: "fixed",
                  inset: 0,
                  zIndex: 10000,
                  background: "rgba(0,0,0,0.5)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#fff",
                  fontSize: 14,
                }}
              >
                问卷编辑器加载中…
              </div>
            }
          >
            <SurveyDesignerModal
              initial={schema}
              title={editId ? "编辑问卷" : "设计问卷"}
              onCancel={() => setDesignerOpen(false)}
              onApply={(next) => {
                setSchema(next);
                setSchemaDirty(true);
                setDesignerOpen(false);
              }}
            />
          </Suspense>
        )}
      </div>
    </AppShell>
  );
}
