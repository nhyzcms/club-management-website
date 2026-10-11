import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { feedbackApi } from "../api/feedback";
import { attachmentApi } from "../api/attachments";
import {
  type FeedbackCategory,
  type FeedbackFormData,
  FEEDBACK_CATEGORY_LABELS,
} from "../types/feedback";
import AppShell from "../components/AppShell";
import { useTurnstile } from "../turnstile";
import "../styles/list.css";

export default function FeedbackPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<{ id: number } | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(true);
  const [fbTitle, setFbTitle] = useState("");
  const [fbCategory, setFbCategory] = useState<FeedbackCategory>("suggestion");
  const [fbDesc, setFbDesc] = useState("");
  const [fbContact, setFbContact] = useState("");
  const [fbSubmitting, setFbSubmitting] = useState(false);
  const [fbSuccess, setFbSuccess] = useState(false);
  const [fbAttributed, setFbAttributed] = useState(false);
  const [fbFiles, setFbFiles] = useState<File[]>([]);
  const [fbUploading, setFbUploading] = useState(false);
  const [fbUploadProgress, setFbUploadProgress] = useState<number | null>(null);

  useEffect(() => {
    api.me()
      .then((d) => setUser({ id: d.user.id }))
      .catch(() => setUser(null));
  }, []);

  const isLoggedIn = !!user;
  const { containerRef, token, reset, enabled, policyReady } = useTurnstile(user === null);

  const submitFeedback = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fbTitle.trim() || !fbDesc.trim()) {
      setError("标题和内容不能为空");
      return;
    }
    if (user === null && enabled && !token) {
      setError("请先完成人机校验。");
      return;
    }
    setFbSubmitting(true);
    setError("");
    const data: FeedbackFormData = {
      title: fbTitle.trim(),
      description: fbDesc.trim(),
      category: fbCategory,
    };
    if (fbContact.trim()) data.contact = fbContact.trim();
    if (fbAttributed) data.disclose_identity = true;
    if (token) data.turnstile_token = token;
    try {
      const created = await feedbackApi.submit(data);
      if (fbAttributed && fbFiles.length) {
        setFbUploading(true);
        for (const f of fbFiles) {
          await attachmentApi.uploadRouted({
            parentType: "feedback",
            parentId: created.id,
            file: f,
            onProgress: setFbUploadProgress,
          });
        }
      }
      setFbSuccess(true);
      setFbTitle("");
      setFbDesc("");
      setFbContact("");
      setFbCategory("suggestion");
      setFbAttributed(false);
      setFbFiles([]);
      setTimeout(() => setFbSuccess(false), 5000);
    } catch (err: any) {
      setError(err.status === 429
        ? "今日提交次数已达上限，请明天再试。"
        : err.message);
      reset();
    } finally {
      setFbSubmitting(false);
      setFbUploading(false);
      setFbUploadProgress(null);
    }
  };

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>意见反馈</span>
          </nav>
          <h1>意见反馈</h1>
          <p className="section-sub">匿名或署名提交建议 / 投诉。举报对象请走内容页上的举报按钮。</p>
        </div>
      </div>

      <div className="container" style={{ paddingBottom: "var(--s-16)" }}>
        {error && (
          <div className="alert alert-danger" role="alert" style={{ margin: "var(--s-6) 0 var(--s-4)" }}>
            <span>{error}</span>
          </div>
        )}

        <section className={"fb-section" + (showForm ? " is-open" : "")}>
          <button className="fb-head" type="button" aria-expanded={showForm} onClick={() => setShowForm((v) => !v)}>
            <div>
              <div className="fb-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5h16v12H7l-3 3z" /></svg>
                提交意见反馈
              </div>
              <div className="fb-hint">可匿名或署名（登录后）提交。署名后方可附媒体。</div>
            </div>
            <span className="fb-toggle">{showForm ? "收起" : "展开"}
              <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
            </span>
          </button>

          {showForm && (
            <div className="fb-body">
              {fbSuccess && (
                <div className="alert alert-success fb-done" role="status">
                  <span>已提交，感谢你的反馈！</span>
                </div>
              )}
              <form onSubmit={submitFeedback}>
                <div className="form-grid">
                  <div className="field">
                    <label className="label">类别</label>
                    <select className="select" value={fbCategory} onChange={(e) => setFbCategory(e.target.value as FeedbackCategory)}>
                      {(Object.keys(FEEDBACK_CATEGORY_LABELS) as FeedbackCategory[]).map((k) => (
                        <option key={k} value={k}>{FEEDBACK_CATEGORY_LABELS[k]}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label className="label">联系方式 <span className="hint">（选填）</span></label>
                    <input className="input" type="text" value={fbContact} onChange={(e) => setFbContact(e.target.value)} placeholder="如需回复请留下联系方式" maxLength={100} />
                  </div>
                </div>
                <div className="field">
                  <label className="label">标题 <span className="hint">*</span></label>
                  <input className="input" type="text" value={fbTitle} onChange={(e) => setFbTitle(e.target.value)} placeholder="一句话概括" maxLength={200} required />
                </div>
                <div className="field">
                  <label className="label">详细内容 <span className="hint">*</span></label>
                  <textarea className="textarea" value={fbDesc} onChange={(e) => setFbDesc(e.target.value)} placeholder="详细描述你的建议或投诉…" rows={4} required />
                </div>
                {isLoggedIn && (
                  <div className="field">
                    <label className="label">署名 <span className="hint">（登录用户）</span></label>
                    <label className="fb-attrib">
                      <input type="checkbox" checked={fbAttributed} onChange={(e) => { setFbAttributed(e.target.checked); if (!e.target.checked) setFbFiles([]); }} />
                      <span>署名提交 —— 处理人可见我的身份，可附带图片 / 视频证据</span>
                    </label>
                    {fbAttributed && (
                      <input type="file" multiple accept="image/*,video/*" onChange={(e) => setFbFiles(Array.from(e.target.files || []))} />
                    )}
                  </div>
                )}
                <div ref={containerRef} />
                <div>
                  <button
                    className="btn btn-primary"
                    type="submit"
                    disabled={fbSubmitting || fbUploading || user === undefined || !policyReady}
                  >
                    {fbUploading ? "上传附件中…" : fbSubmitting ? "提交中…" : fbAttributed ? "署名提交" : "匿名提交"}
                  </button>
                </div>
                {fbUploadProgress != null && (
                  <div style={{ height: 6, background: "#e5e7eb", borderRadius: 4, overflow: "hidden", margin: "8px 0 0" }} aria-label="上传进度">
                    <div style={{ width: `${Math.round(fbUploadProgress * 100)}%`, height: "100%", background: "#2563eb", transition: "width .2s" }} />
                  </div>
                )}
              </form>
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
