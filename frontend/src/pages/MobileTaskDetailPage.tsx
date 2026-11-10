import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { attachmentApi } from "../api/attachments";
import { taskApi } from "../api/tasks";
import CommentSection from "../components/CommentSection";
import MobilePage from "../components/MobilePage";
import RichTextEditor from "../components/RichTextEditor";
import {
  PRIORITY_COLORS,
  PRIORITY_LABELS,
  STATUS_BADGE_CLASS,
  STATUS_LABELS,
  type TaskAction,
  type TaskDetail,
} from "../types/tasks";
import "../styles/comments.css";
import "../styles/mobile-work.css";

/**
 * 手机版任务详情（/#/m/tasks/:id）。
 *
 * 与桌面同源：动作按钮完全由后端 available_actions 决定（不在前端推状态机），
 * 认领 / 验收 / 打回 / 取消的接口一致。手机版只做信息分层：
 * 头部摘要 → 动作 → 描述 → 认领 → 附件 → 评论。
 */

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

export default function MobileTaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [claimReason, setClaimReason] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [attUploading, setAttUploading] = useState(false);
  const [attProgress, setAttProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    taskApi
      .get(Number(id))
      .then((t) => {
        setTask(t);
        document.title = `${t.title} · 任务`;
      })
      .catch((e: any) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false));
  }, [id]);

  const reload = async () => {
    if (!task) return;
    setTask(await taskApi.get(task.id));
  };

  const run = async (fn: () => Promise<TaskDetail>) => {
    setActionLoading(true);
    setError("");
    try {
      setTask(await fn());
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setActionLoading(false);
    }
  };

  const handleClaim = async () => {
    if (!task) return;
    setClaiming(true);
    setError("");
    try {
      await taskApi.claim(task.id, claimReason);
      await reload();
      setClaimReason("");
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setClaiming(false);
    }
  };

  const handleApproveClaim = async (claimId: number) => {
    if (!task) return;
    setActionLoading(true);
    try {
      setTask(await taskApi.approveClaim(task.id, claimId));
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRejectClaim = async (claimId: number) => {
    if (!task) return;
    setActionLoading(true);
    try {
      await taskApi.rejectClaim(task.id, claimId);
      await reload();
    } catch (e: any) {
      setError(e?.message || "操作失败");
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
      setTask(await taskApi.rejectCompletion(task.id, reason));
      setShowRejectForm(false);
      setRejectReason("");
    } catch (e: any) {
      setError(e?.message || "操作失败");
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
      const att = await attachmentApi.uploadRouted({
        parentType: "task",
        parentId: task.id,
        file,
        onProgress: setAttProgress,
      });
      if (att) setTask({ ...task, attachments: [...task.attachments, att] });
      else setTask(await taskApi.get(task.id)); // tus：服务端 finished 钩子异步建附件
    } catch (err: any) {
      setError(err?.message || "上传失败");
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
    } catch (e: any) {
      setError(e?.message || "删除失败");
    }
  };

  if (loading) {
    return (
      <MobilePage title="任务详情" back="/m/tasks">
        <p className="mw-hint">加载中…</p>
      </MobilePage>
    );
  }
  if (!task) {
    return (
      <MobilePage title="任务详情" back="/m/tasks">
        <p className="mw-alert">{error || "任务不存在"}</p>
      </MobilePage>
    );
  }

  const available = task.available_actions ?? [];
  const can = (action: TaskAction) => available.includes(action);
  const pendingClaims = task.claim_requests.filter((c) => c.status === "pending");

  return (
    <MobilePage
      title="任务详情"
      back="/m/tasks"
      actions={
        task.status === "pending" ? (
          <Link className="mw-link" to={`/tasks/${task.id}/edit`}>编辑</Link>
        ) : undefined
      }
    >
      <div className="mw-detail-head">
        <div className="mw-card-meta" style={{ marginTop: 0 }}>
          <span className={"badge " + STATUS_BADGE_CLASS[task.status]}>
            {STATUS_LABELS[task.status]}
          </span>
          <span className="mw-prio" style={{ color: PRIORITY_COLORS[task.priority] }}>
            {PRIORITY_LABELS[task.priority]}
          </span>
        </div>
        <h2 className="mw-detail-title">{task.title}</h2>
        <p className="mw-detail-sub">
          创建人 {task.creator.nickname || task.creator.username} · 负责人{" "}
          {task.assignee ? task.assignee.nickname || task.assignee.username : "未分配"} ·{" "}
          {new Date(task.created_at).toLocaleDateString("zh-CN")}
        </p>
        {task.tags.length > 0 && (
          <div className="mw-tags" style={{ marginTop: 8 }}>
            {task.tags.map((t) => (
              <span key={t.id} className="tag-mini" style={{ backgroundColor: t.color + "1a", color: t.color }}>
                {t.name}
              </span>
            ))}
          </div>
        )}
      </div>

      {error && <div className="mw-alert">{error}</div>}

      {task.status === "in_progress" && task.reject_reason && (
        <div className="mw-alert">此任务已被打回：{task.reject_reason}</div>
      )}

      {(can("complete") || can("approve_completion") || can("reject_completion") || can("cancel")) && (
        <div className="mw-section">
          <h2>你可以做什么</h2>
          <div className="mw-actions" style={{ marginTop: 0 }}>
            {can("complete") && (
              <button
                type="button"
                className="mw-btn mw-btn-primary"
                disabled={actionLoading}
                onClick={() => void run(() => taskApi.complete(task.id))}
              >
                {actionLoading ? "处理中…" : "提交验收"}
              </button>
            )}
            {can("approve_completion") && (
              <button
                type="button"
                className="mw-btn mw-btn-primary"
                disabled={actionLoading}
                onClick={() => void run(() => taskApi.approveCompletion(task.id))}
              >
                通过验收
              </button>
            )}
            {can("reject_completion") && (
              <button
                type="button"
                className="mw-btn mw-btn-ghost"
                disabled={actionLoading}
                onClick={() => setShowRejectForm((v) => !v)}
              >
                打回
              </button>
            )}
            {can("cancel") && (
              <button
                type="button"
                className="mw-btn mw-btn-danger mw-danger"
                disabled={actionLoading}
                onClick={() => void run(() => taskApi.cancel(task.id))}
              >
                取消任务
              </button>
            )}
          </div>
          {showRejectForm && can("reject_completion") && (
            <div className="mw-field">
              <label className="mw-label">打回理由</label>
              <textarea
                className="mw-textarea"
                rows={3}
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="说明打回原因，告知负责人需返工的内容…"
              />
              <div className="mw-actions">
                <button
                  type="button"
                  className="mw-btn mw-btn-ghost"
                  disabled={actionLoading}
                  onClick={() => {
                    setShowRejectForm(false);
                    setRejectReason("");
                  }}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="mw-btn mw-btn-primary"
                  disabled={actionLoading}
                  onClick={handleRejectCompletion}
                >
                  确认打回
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="mw-section">
        <h2>描述</h2>
        {task.description ? (
          /* 复用桌面同一个只读编辑器：任务描述后端未做 HTML 净化，
             直接 dangerouslySetInnerHTML 会引入存储型 XSS；Tiptap 只重建
             白名单节点，与桌面渲染一致。 */
          <div className="mw-rte">
            <RichTextEditor content={task.description} editable={false} />
          </div>
        ) : (
          <p className="mw-hint" style={{ marginBottom: 0 }}>暂无描述</p>
        )}
      </div>

      {task.collaborators.length > 0 && (
        <div className="mw-section">
          <h2>协作者</h2>
          <div className="mw-card-meta" style={{ marginTop: 0 }}>
            {task.collaborators.map((u) => (
              <Link key={u.id} to={`/u/${u.id}`} className="badge badge-neutral">
                {u.nickname || u.username}
              </Link>
            ))}
          </div>
        </div>
      )}

      {can("claim") && (
        <div className="mw-section">
          <h2>认领任务</h2>
          <textarea
            className="mw-textarea"
            rows={2}
            value={claimReason}
            onChange={(e) => setClaimReason(e.target.value)}
            placeholder="说明你想认领此任务的理由…"
          />
          <div className="mw-actions">
            <button
              type="button"
              className="mw-btn mw-btn-primary"
              disabled={claiming}
              onClick={handleClaim}
            >
              {claiming ? "提交中…" : "申请认领"}
            </button>
          </div>
        </div>
      )}

      {can("approve_claim") && pendingClaims.length > 0 && (
        <div className="mw-section">
          <h2>认领请求（{pendingClaims.length}）</h2>
          {pendingClaims.map((cr) => (
            <div key={cr.id} className="mw-claim">
              <div className="mw-claim-head">
                <strong>{cr.claimant.nickname || cr.claimant.username}</strong>
                <span className="mw-detail-sub" style={{ marginTop: 0 }}>
                  {new Date(cr.created_at).toLocaleString("zh-CN")}
                </span>
              </div>
              {cr.reason && <div className="mw-claim-reason">{cr.reason}</div>}
              <div className="mw-actions">
                <button
                  type="button"
                  className="mw-btn mw-btn-primary"
                  disabled={actionLoading}
                  onClick={() => void handleApproveClaim(cr.id)}
                >
                  批准
                </button>
                <button
                  type="button"
                  className="mw-btn mw-btn-ghost"
                  disabled={actionLoading}
                  onClick={() => void handleRejectClaim(cr.id)}
                >
                  拒绝
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mw-section">
        <div className="mw-toolbar" style={{ marginBottom: 0 }}>
          <h2 style={{ flex: "1 1 auto", margin: 0, fontFamily: "var(--font-display)", fontSize: 14 }}>
            附件（{task.attachments.length}）
          </h2>
          <button
            type="button"
            className="mw-btn mw-btn-ghost"
            style={{ minHeight: 34, padding: "6px 12px", fontSize: 13 }}
            disabled={attUploading}
            onClick={() => fileInputRef.current?.click()}
          >
            + 上传
          </button>
          <input ref={fileInputRef} type="file" onChange={handleFileUpload} style={{ display: "none" }} />
        </div>
        {attUploading && (
          <div className="mw-hint" style={{ marginTop: 8, marginBottom: 0 }}>
            {attProgress != null ? `上传 ${Math.round(attProgress * 100)}%` : "上传中…"}
            <div className="mw-progress">
              <i style={{ width: attProgress != null ? `${Math.round(attProgress * 100)}%` : "0%" }} />
            </div>
          </div>
        )}
        {task.attachments.length === 0 ? (
          <p className="mw-hint" style={{ marginTop: 8, marginBottom: 0 }}>暂无附件</p>
        ) : (
          <div style={{ marginTop: 6 }}>
            {task.attachments.map((att) => (
              <div key={att.id} className="mw-att">
                <a
                  className="mw-att-name"
                  href={att.file_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {att.file_name}
                </a>
                <span className="mw-att-size">{formatSize(att.file_size)}</span>
                <button
                  type="button"
                  className="mw-link"
                  style={{ color: "var(--danger)" }}
                  aria-label={`删除附件 ${att.file_name}`}
                  onClick={() => void handleDeleteAttachment(att.id)}
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <CommentSection host={{ task: task.id }} />
    </MobilePage>
  );
}
