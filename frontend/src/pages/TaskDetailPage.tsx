import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { taskApi } from "../api/tasks";
import { attachmentApi } from "../api/attachments";
import {
  TaskDetail, TaskAction,
  STATUS_LABELS, PRIORITY_LABELS,
  STATUS_BADGE_CLASS, PRIORITY_DOT_CLASS,
} from "../types/tasks";
import RichTextEditor from "../components/RichTextEditor";
import Avatar from "../components/Avatar";
import AppShell from "../components/AppShell";
import CommentSection from "../components/CommentSection";
import "../styles/detail.css";

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [claimReason, setClaimReason] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [attUploading, setAttUploading] = useState(false);
  const [attProgress, setAttProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    taskApi.get(Number(id))
      .then((t) => {
        setTask(t);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  const reloadTask = async () => {
    if (!task) return;
    const updated = await taskApi.get(task.id);
    setTask(updated);
  };

  const handleClaim = async () => {
    if (!task) return;
    setClaiming(true);
    try {
      await taskApi.claim(task.id, claimReason);
      await reloadTask();
      setClaimReason("");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setClaiming(false);
    }
  };

  const handleApproveClaim = async (claimId: number) => {
    if (!task) return;
    setActionLoading(true);
    try {
      const updated = await taskApi.approveClaim(task.id, claimId);
      setTask(updated);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleRejectClaim = async (claimId: number) => {
    if (!task) return;
    setActionLoading(true);
    try {
      await taskApi.rejectClaim(task.id, claimId);
      await reloadTask();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleComplete = async () => {
    if (!task) return;
    setActionLoading(true);
    try {
      const updated = await taskApi.complete(task.id);
      setTask(updated);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleApproveCompletion = async () => {
    if (!task) return;
    setActionLoading(true);
    try {
      const updated = await taskApi.approveCompletion(task.id);
      setTask(updated);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleRejectCompletion = async () => {
    if (!task) return;
    const reason = rejectReason.trim();
    if (!reason) {
      setError("请填写打回理由");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await taskApi.rejectCompletion(task.id, reason);
      setTask(updated);
      setShowRejectForm(false);
      setRejectReason("");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!task) return;
    setActionLoading(true);
    try {
      const updated = await taskApi.cancel(task.id);
      setTask(updated);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !task) return;
    setAttUploading(true);
    setAttProgress(null);
    try {
      // 按大小自动选路：≤50MB 同步、>50MB tus 可续传
      const att = await attachmentApi.uploadRouted({
        parentType: "task", parentId: task.id, file, onProgress: setAttProgress,
      });
      if (att) {
        setTask({ ...task, attachments: [...task.attachments, att] });
      } else {
        setTask(await taskApi.get(task.id));  // tus：附件由服务端 finished 钩子异步建，重新拉取
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setAttUploading(false);
      setAttProgress(null);
    }
    e.target.value = "";
  };

  const handleDeleteAttachment = async (attachmentId: number) => {
    if (!task) return;
    try {
      await attachmentApi.delete(attachmentId);
      setTask({ ...task, attachments: task.attachments.filter((a) => a.id !== attachmentId) });
    } catch (err: any) {
      setError(err.message);
    }
  };

  const formatDate = (d: string | null) => {
    if (!d) return "-";
    return new Date(d).toLocaleDateString("zh-CN");
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  };

  // 按钮显隐完全由后端 available_actions 决定（任务生命周期模块，#6/#15）；
  // 前端不再凭 currentUser + 状态本地推 canX，编辑锁除外（仅 pending 可编辑，#6 故事 31）。
  const availableActions = task?.available_actions ?? [];
  const can = (action: TaskAction) => availableActions.includes(action);
  const pendingClaims = task?.claim_requests.filter((c) => c.status === "pending") || [];

  if (loading) return <AppShell><div className="container detail-container detail-body"><p className="empty-text">加载中…</p></div></AppShell>;
  if (error && !task) return <AppShell><div className="container detail-container detail-body"><p className="empty-text">{error}</p></div></AppShell>;
  if (!task) return <AppShell><div className="container detail-container detail-body"><p className="empty-text">任务不存在</p></div></AppShell>;

  return (
    <AppShell>
      <div className="page-head">
        <div className="container detail-container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/tasks"); }}>任务</a>
            <span className="sep">/</span>
            <span>{task.title}</span>
          </nav>
          <div className="detail-head-row">
            <div className="detail-head-main">
              <span className={"prio-dot " + PRIORITY_DOT_CLASS[task.priority]}
                    title={"优先级：" + PRIORITY_LABELS[task.priority]} />
              <h1 className="detail-title">{task.title}</h1>
              <span className={"badge " + STATUS_BADGE_CLASS[task.status]}>
                <span className="badge-dot" />{STATUS_LABELS[task.status]}
              </span>
            </div>
            <div className="detail-head-actions">
              {task.status === "pending" && (
                <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/tasks/${task.id}/edit`)}>编辑</button>
              )}
              <button className="btn btn-ghost btn-sm" onClick={() => navigate("/tasks")}>返回列表</button>
            </div>
          </div>
          <p className="detail-sub">
            {PRIORITY_LABELS[task.priority]} · 创建人 {task.creator.nickname || task.creator.username}
            {" · 负责人 "}{task.assignee ? (task.assignee.nickname || task.assignee.username) : "未分配"}
            {" · "}{formatDate(task.created_at)}
          </p>
        </div>
      </div>

      <div className="container detail-container detail-body">
        {error && <div className="alert alert-danger">{error}</div>}

        {task.status === "in_progress" && task.reject_reason && (
          <div className="alert alert-warning"><b>此任务已被打回：</b>{task.reject_reason}</div>
        )}

        {(can("complete") || can("approve_completion") || can("reject_completion") || can("cancel")) && (
          <div className="detail-actions">
            {can("complete") && (
              <button className="btn btn-primary" onClick={handleComplete} disabled={actionLoading}>
                {actionLoading ? "处理中…" : "提交验收"}
              </button>
            )}
            {(can("approve_completion") || can("reject_completion")) && (
              <>
                <button className="btn btn-primary" onClick={handleApproveCompletion} disabled={actionLoading}>通过验收</button>
                <button className="btn btn-ghost" onClick={() => setShowRejectForm(true)} disabled={actionLoading}>打回</button>
              </>
            )}
            {can("cancel") && (
              <button className="btn btn-ghost" onClick={handleCancel} disabled={actionLoading}>取消任务</button>
            )}
          </div>
        )}

        {showRejectForm && can("reject_completion") && (
          <div className="card card-pad detail-section">
            <h3 className="section-h">打回理由</h3>
            <textarea className="textarea" value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder="说明打回原因，告知负责人需返工的内容…" rows={3} />
            <div className="detail-row">
              <button className="btn btn-primary" onClick={handleRejectCompletion} disabled={actionLoading}>
                {actionLoading ? "处理中…" : "确认打回"}
              </button>
              <button className="btn btn-ghost"
                      onClick={() => { setShowRejectForm(false); setRejectReason(""); }}
                      disabled={actionLoading}>取消</button>
            </div>
          </div>
        )}

        {task.tags.length > 0 && (
          <div className="detail-tags">
            {task.tags.map((t) => (
              <span key={t.id} className="tag-mini" style={{ backgroundColor: t.color + "1a", color: t.color }}>{t.name}</span>
            ))}
          </div>
        )}

        <div className="card card-pad detail-section">
          <h3 className="section-h">描述</h3>
          {task.description ? (
            <RichTextEditor content={task.description} editable={false} />
          ) : (
            <p className="empty-text">暂无描述</p>
          )}
        </div>

        {task.collaborators.length > 0 && (
          <div className="card card-pad detail-section">
            <h3 className="section-h">协作者</h3>
            <div className="chip-row">
              {task.collaborators.map((u) => (
                <span key={u.id} className="user-chip-inline">
                  <Link to={`/u/${u.id}`}><Avatar user={u} size="sm" /></Link>{u.nickname || u.username}
                </span>
              ))}
            </div>
          </div>
        )}

        {can("claim") && (
          <div className="card card-pad detail-section">
            <h3 className="section-h">认领任务</h3>
            <textarea className="textarea" value={claimReason}
                      onChange={(e) => setClaimReason(e.target.value)}
                      placeholder="说明你想认领此任务的理由…" rows={2} />
            <button className="btn btn-primary" onClick={handleClaim} disabled={claiming}>
              {claiming ? "提交中…" : "申请认领"}
            </button>
          </div>
        )}

        {can("approve_claim") && pendingClaims.length > 0 && (
          <div className="card card-pad detail-section">
            <h3 className="section-h">认领请求 ({pendingClaims.length})</h3>
            <div className="claim-list">
              {pendingClaims.map((cr) => (
                <div key={cr.id} className="claim-item">
                  <div className="claim-head">
                    <Link to={`/u/${cr.claimant.id}`}><Avatar user={cr.claimant} size="sm" /></Link>
                    <strong>{cr.claimant.nickname || cr.claimant.username}</strong>
                    <span className="claim-time">{new Date(cr.created_at).toLocaleString("zh-CN")}</span>
                  </div>
                  {cr.reason && <div className="claim-reason">{cr.reason}</div>}
                  <div className="detail-row">
                    <button className="btn btn-primary btn-sm" onClick={() => handleApproveClaim(cr.id)} disabled={actionLoading}>批准</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => handleRejectClaim(cr.id)} disabled={actionLoading}>拒绝</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="card card-pad detail-section">
          <div className="section-head-row">
            <h3 className="section-h">附件 ({task.attachments.length})</h3>
            <button className="btn btn-secondary btn-sm" onClick={() => fileInputRef.current?.click()} disabled={attUploading}>+ 上传</button>
            <input ref={fileInputRef} type="file" onChange={handleFileUpload} style={{ display: "none" }} />
          </div>
          {attUploading && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
              <span>{attProgress != null ? `上传 ${Math.round(attProgress * 100)}%` : "上传中…"}</span>
              <div style={{ flex: 1, height: 6, background: "#e5e7eb", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: attProgress != null ? `${Math.round(attProgress * 100)}%` : "0%", height: "100%", background: "#2563eb", transition: "width .2s" }} />
              </div>
            </div>
          )}
          {task.attachments.length > 0 ? (
            <div className="att-list">
              {task.attachments.map((att) => (
                <div key={att.id} className="att-item">
                  <span className="att-icon">
                    {att.file_type === "image" ? "IMG" : att.file_type === "video" ? "VID" :
                     att.file_type === "document" ? "DOC" : att.file_type === "archive" ? "ZIP" : "FILE"}
                  </span>
                  <a href={att.file_url} target="_blank" rel="noopener noreferrer" className="att-name">{att.file_name}</a>
                  <span className="att-size">{formatSize(att.file_size)}</span>
                  <button className="att-del" onClick={() => handleDeleteAttachment(att.id)} title="删除">✕</button>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-text">暂无附件</p>
          )}
        </div>

        <CommentSection host={{ task: task.id }} />
      </div>
    </AppShell>
  );
}
