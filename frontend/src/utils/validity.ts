/**
 * 账号有效期（ADR-0041）前端口径：类型、展示格式、事件名。
 *
 * 与 ``accounts/validity_summary.py`` 的响应一一对应；放在 utils 里是为了让
 * 认证面板 / 弹窗 / 宿主都能引用，而不必互相 import 组件。
 */

/** 认证动作成功后 dispatch：宿主据此重新拉快照，通过认证会弹一次有效期说明。 */
export const VALIDITY_CHANGED_EVENT = "club:validity-changed";

export interface ValidityChannel {
  channel: string;
  label: string;
  expires_at: string | null;
  remaining_days: number | null;
}

export interface ValiditySummary {
  status: "permanent" | "admin" | "verified" | "expired" | "unverified";
  status_label: string;
  expires_at: string | null;
  remaining_days: number | null;
  registration_deadline: string | null;
  channels: ValidityChannel[];
  policy: {
    verification_valid_days: number;
    admin_valid_days: number;
    registration_verify_days: number;
  };
  key: string;
  notice_pending: boolean;
}

/** 到期时间统一按本地时区展示；`null` = 永久。 */
export function formatExpiry(iso: string | null): string {
  if (!iso) return "永久有效";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 剩余有效期：`null` = 永久；0 = 不足 24 小时；负数 = 已到期。 */
export function formatRemaining(days: number | null, expiresAt: string | null): string {
  if (days === null) return "永久有效";
  if (days > 0) return `${days} 天`;
  if (days === 0) {
    const at = expiresAt ? new Date(expiresAt).getTime() : 0;
    return at && at > Date.now() ? "不足 1 天" : "已到期";
  }
  return "已到期";
}
