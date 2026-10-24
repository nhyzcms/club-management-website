import type { PasswordResetRequestItem } from "../../types/passwordReset";
import {
  PASSWORD_RESET_STATUS_BADGE,
  PASSWORD_RESET_STATUS_LABELS,
} from "../../types/passwordReset";

/**
 * 审核台「密码重置」桌的单条视图（桌面 / 手机共用）。
 *
 * 只负责展示与回调，取数 / 前进 / 权限在各自页面（与身份桌同构）。
 */
export default function PasswordResetPane({
  item,
  busy,
  loading,
  flash,
  onApprove,
  onReject,
  onNext,
  onLightbox,
}: {
  item: PasswordResetRequestItem;
  busy: boolean;
  loading: boolean;
  flash: string;
  onApprove: () => void;
  onReject: () => void;
  onNext: () => void;
  onLightbox: (url: string) => void;
}) {
  const submitted = new Date(item.created_at).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="desk-pane">
      <div className="desk-meta">
        <span className={"badge " + PASSWORD_RESET_STATUS_BADGE[item.status]}>
          {PASSWORD_RESET_STATUS_LABELS[item.status]}
        </span>
        <span className="type-tag fb">密码重置</span>
        {flash && <span className="badge badge-brand">{flash}</span>}
      </div>
      <h2 className="desk-title">{item.real_name || item.username}</h2>
      <div className="desk-sub">
        <span>用户名 {item.username}</span>
        <span className="sep">·</span>
        <span>{submitted} 提交</span>
        {item.contact && (
          <>
            <span className="sep">·</span>
            <span>联系 {item.contact}</span>
          </>
        )}
        {item.reviewed_by && (
          <>
            <span className="sep">·</span>
            <span>处理人 @{item.reviewed_by.username}</span>
          </>
        )}
      </div>

      <div className="desk-sub" style={{ marginTop: 8 }}>
        <span>申请填写：{item.identifier || "（未填写）"}</span>
        {item.reset_at && (
          <>
            <span className="sep">·</span>
            <span>已重置密码</span>
          </>
        )}
      </div>

      {item.note && (
        <div className="plain-text" style={{ margin: "12px 0" }}>
          {item.note}
        </div>
      )}

      <p className="empty-text" style={{ marginTop: 8 }}>
        身份证明（点击查看大图）：
      </p>
      <div className="desk-proofs">
        <button
          type="button"
          className="desk-proof"
          onClick={() => onLightbox(item.proof_url)}
          aria-label="查看完整身份证明"
        >
          <img src={item.proof_url} alt="密码重置身份证明" width={1200} height={1600} loading="lazy" />
          <span className="desk-proof-time">{submitted} 上传</span>
        </button>
      </div>

      {item.status === "pending" && (
        <p className="hint" style={{ marginTop: 12 }}>
          批准后密码将重置为 <b>123456</b>，对方所有设备立即下线，且首次登录必须修改密码。
        </p>
      )}
      {item.review_note && (
        <p className="hint" style={{ marginTop: 8 }}>
          处理说明：{item.review_note}
        </p>
      )}

      <div className="desk-actions">
        {item.status === "pending" && (
          <>
            <button className="btn btn-primary" disabled={busy} onClick={onApprove}>
              批准重置
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={onReject}>
              驳回
            </button>
          </>
        )}
        <button className="btn btn-ghost" disabled={busy || loading} onClick={onNext}>
          下一条
        </button>
      </div>
    </div>
  );
}
