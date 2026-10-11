import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { feedbackApi } from "../api/feedback";
import { attachmentApi } from "../api/attachments";
import { api } from "../api/client";
import {
  type FeedbackDetail,
  FEEDBACK_CATEGORY_LABELS,
  FEEDBACK_STATUS_LABELS,
  FEEDBACK_STATUS_BADGE,
} from "../types/feedback";
import Avatar from "../components/Avatar";
import AppShell from "../components/AppShell";
import "../styles/detail.css";

export default function FeedbackDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [item, setItem] = useState<FeedbackDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [currentUser, setCurrentUser] = useState<{ id: number; can_view_feedback?: boolean } | null>(null);
  const [attUploading, setAttUploading] = useState(false);
  const [attProgress, setAttProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.me().then((d) => setCurrentUser({
      id: d.user.id,
      can_view_feedback: d.user.permissions?.can_view_feedback,
    })).catch(() => {});
  }, []);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    feedbackApi.get(Number(id))
      .then(setItem)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  const canViewFeedback = !!currentUser?.can_view_feedback;
  const isCreator = !!item && !!currentUser && item.creator?.id === currentUser.id;
  const canDeleteAttachment = canViewFeedback || isCreator;
  const canUploadAttachment = isCreator && item?.status === "pending";

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !item) return;
    setAttUploading(true);
    setAttProgress(null);
    try {
      const att = await attachmentApi.uploadRouted({
        parentType: "feedback", parentId: item.id, file, onProgress: setAttProgress,
      });
      if (att) {
        setItem({ ...item, attachments: [...item.attachments, att] });
      } else {
        setItem(await feedbackApi.get(item.id));
      }
    } catch (err: any) { setError(err.message); }
    finally { setAttUploading(false); setAttProgress(null); }
    e.target.value = "";
  };

  const handleDeleteAttachment = async (attachmentId: number) => {
    if (!item) return;
    try {
      await attachmentApi.delete(attachmentId);
      setItem({ ...item, attachments: item.attachments.filter((a) => a.id !== attachmentId) });
    } catch (err: any) { setError(err.message); }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  };

  if (loading) return <AppShell><div className="container detail-container detail-body"><p className="empty-text">加载中…</p></div></AppShell>;
  if (error && !item) return <AppShell><div className="container detail-container detail-body"><p className="empty-text">{error}</p></div></AppShell>;
  if (!item) return <AppShell><div className="container detail-container detail-body"><p className="empty-text">反馈不存在或无权查看</p></div></AppShell>;

  const p = item;

  return (
    <AppShell>
      <div className="page-head">
        <div className="container detail-container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/feedback"); }}>意见反馈</a>
            <span className="sep">/</span>
            <span>{p.title}</span>
          </nav>
          <div className="detail-head-row">
            <div className="detail-head-main">
              <h1 className="detail-title">{p.title}</h1>
              <span className={"badge " + FEEDBACK_STATUS_BADGE[p.status]}>
                <span className="badge-dot" />{FEEDBACK_STATUS_LABELS[p.status]}
              </span>
            </div>
            <div className="detail-head-actions">
              <button className="btn btn-ghost btn-sm" onClick={() => navigate("/feedback")}>返回</button>
            </div>
          </div>
          <p className="detail-sub">
            {FEEDBACK_CATEGORY_LABELS[p.category] || "反馈"}
            {" · "}提交人 {p.creator ? (p.creator.nickname || p.creator.username) : "匿名"}
            {" · "}{new Date(p.created_at).toLocaleDateString("zh-CN")}
          </p>
        </div>
      </div>

      <div className="container detail-container detail-body">
        {error && <div className="alert alert-danger">{error}</div>}

        {p.status === "closed" && p.close_note && (
          <div className="alert alert-success"><b>了结说明：</b>{p.close_note}</div>
        )}

        <div className="card card-pad detail-section">
          <h3 className="section-h">基本信息</h3>
          <div className="meta-grid">
            <div className="meta-cell"><span className="meta-k">反馈类别</span><span className="meta-v">{FEEDBACK_CATEGORY_LABELS[p.category] || "-"}</span></div>
            <div className="meta-cell"><span className="meta-k">提交人</span><span className="meta-v">{p.creator ? (p.creator.nickname || p.creator.username) : "匿名"}</span></div>
            {p.contact && canViewFeedback && (
              <div className="meta-cell"><span className="meta-k">联系方式</span><span className="meta-v">{p.contact}</span></div>
            )}
            <div className="meta-cell"><span className="meta-k">提交时间</span><span className="meta-v">{new Date(p.created_at).toLocaleString("zh-CN")}</span></div>
            {p.closed_by && (
              <div className="meta-cell">
                <span className="meta-k">了结人</span>
                <span className="meta-v user-with-avatar"><Link to={`/u/${p.closed_by.id}`}><Avatar user={p.closed_by} size="sm" /></Link>{p.closed_by.nickname || p.closed_by.username}</span>
              </div>
            )}
          </div>
        </div>

        <div className="card card-pad detail-section">
          <h3 className="section-h">详细内容</h3>
          {p.description ? (
            <div className="plain-text">{p.description}</div>
          ) : (
            <p className="empty-text">暂无内容</p>
          )}
        </div>

        <div className="card card-pad detail-section">
          <div className="section-head-row">
            <h3 className="section-h">附件 ({p.attachments.length})</h3>
            {canUploadAttachment && (
              <>
                <button className="btn btn-secondary btn-sm" onClick={() => fileInputRef.current?.click()} disabled={attUploading}>+ 上传</button>
                <input ref={fileInputRef} type="file" onChange={handleFileUpload} style={{ display: "none" }} />
              </>
            )}
          </div>
          {attUploading && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
              <span>{attProgress != null ? `上传 ${Math.round(attProgress * 100)}%` : "上传中…"}</span>
              <div style={{ flex: 1, height: 6, background: "#e5e7eb", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: attProgress != null ? `${Math.round(attProgress * 100)}%` : "0%", height: "100%", background: "#2563eb", transition: "width .2s" }} />
              </div>
            </div>
          )}
          {p.attachments.length > 0 ? (
            <div className="att-list">
              {p.attachments.map((att) => (
                <div key={att.id} className="att-item">
                  <span className="att-icon">
                    {att.file_type === "image" ? "IMG" : att.file_type === "video" ? "VID" :
                     att.file_type === "document" ? "DOC" : att.file_type === "archive" ? "ZIP" : "FILE"}
                  </span>
                  <a href={att.file_url} target="_blank" rel="noopener noreferrer" className="att-name">{att.file_name}</a>
                  <span className="att-size">{formatSize(att.file_size)}</span>
                  {canDeleteAttachment && (
                    <button className="att-del" onClick={() => handleDeleteAttachment(att.id)} title="删除">✕</button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-text">暂无附件</p>
          )}
        </div>
      </div>
    </AppShell>
  );
}
