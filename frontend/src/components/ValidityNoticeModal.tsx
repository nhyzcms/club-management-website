import { useEffect } from "react";
import {
  formatExpiry,
  formatRemaining,
  type ValiditySummary,
} from "../utils/validity";

/**
 * 账号有效期说明弹窗（ADR-0041）：注册成功 / 认证通过后各弹一次，写回服务端的
 * ``Profile.validity_notice_ack`` 后不再打扰；续期或重新认证会再次出现。
 *
 * 内容三件套：到期时间、剩余有效期、有效期规则（天数取后台 SiteSettings 实时值）。
 */
export default function ValidityNoticeModal({
  data,
  onClose,
}: {
  data: ValiditySummary;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const { status, policy } = data;
  const permanent = status === "permanent" || data.expires_at === null;
  const expiresLabel =
    status === "unverified" ? "认证截止时间" : status === "admin" ? "管理员身份到期时间" : "账号到期时间";

  const lead =
    status === "permanent"
      ? "你的账号为超级管理员，永久有效，不设到期时间。"
      : status === "admin"
        ? "你的管理员身份按下列时间到期；到期后会自动撤销管理员身份（账号仍保留）。"
        : status === "expired"
          ? `你的身份认证已于 ${formatExpiry(data.expires_at)} 到期，账号已回落为未认证，请尽快重新认证。`
          : status === "unverified"
            ? "你的账号尚未完成认证。请在认证截止前完成任一认证，否则账号将被停用。"
            : "你的账号已通过认证，有效期如下。到期后账号会回落为未认证，重新认证即可恢复。";

  const rules = [
    `认证有效期 ${policy.verification_valid_days} 天：完成邮箱认证、学生证人工核验或认证码兑换任一通道后生效；到期后回落为未认证，重新认证即可恢复。`,
    `管理员委任有效期 ${policy.admin_valid_days} 天：到期自动撤销管理员身份，需要续期请联系社长。`,
    `注册宽限 ${policy.registration_verify_days} 天：注册后须在宽限期内完成任一认证，逾期未认证的账号将被停用（需联系管理员恢复）。`,
  ];

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label="账号有效期"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 10000,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)",
          color: "var(--fg)",
          borderRadius: 8,
          padding: 24,
          width: 460,
          maxWidth: "100%",
          maxHeight: "85vh",
          overflowY: "auto",
          boxShadow: "0 8px 30px rgba(0,0,0,0.25)",
        }}
      >
        <h3 style={{ margin: "0 0 8px", fontSize: 18 }}>账号有效期</h3>
        <p style={{ color: "var(--muted)", lineHeight: 1.7, margin: "0 0 16px", fontSize: 14 }}>
          {lead}
        </p>

        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: 6,
            padding: "10px 14px",
            marginBottom: 16,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "4px 0", fontSize: 14 }}>
            <span style={{ color: "var(--muted)" }}>{expiresLabel}</span>
            <b className="tnum">
              {permanent && status !== "unverified" ? "永久有效" : formatExpiry(data.expires_at)}
            </b>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "4px 0", fontSize: 14 }}>
            <span style={{ color: "var(--muted)" }}>剩余有效期</span>
            <b className="tnum">
              {permanent && status !== "unverified"
                ? "永久有效"
                : formatRemaining(data.remaining_days, data.expires_at)}
            </b>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "4px 0", fontSize: 14 }}>
            <span style={{ color: "var(--muted)" }}>当前身份</span>
            <b>{data.status_label}</b>
          </div>
          {data.channels.length > 1 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, color: "var(--muted)", fontSize: 13, lineHeight: 1.7 }}>
              {data.channels.map((c) => (
                <li key={c.channel}>
                  {c.label}：{formatExpiry(c.expires_at)}（
                  {formatRemaining(c.remaining_days, c.expires_at)}）
                </li>
              ))}
            </ul>
          )}
        </div>

        <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>有效期规则</h4>
        <ol style={{ margin: "0 0 18px", paddingLeft: 20, color: "var(--muted)", fontSize: 13, lineHeight: 1.8 }}>
          {rules.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ol>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-primary" onClick={onClose}>
            我知道了
          </button>
        </div>
      </div>
    </div>
  );
}
