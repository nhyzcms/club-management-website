export type PasswordResetStatus = "pending" | "approved" | "rejected";

/** 审核台「密码重置」桌的一行（对应 accounts.PasswordResetRequest）。 */
export interface PasswordResetRequestItem {
  id: number;
  user_id: number;
  username: string;
  real_name: string;
  identifier: string;
  contact: string;
  note: string;
  status: PasswordResetStatus;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: { id: number; username: string } | null;
  review_note: string;
  reset_at: string | null;
  /** 带鉴权的证明图地址（仅本人 / 审批人可读）。 */
  proof_url: string;
}

export const PASSWORD_RESET_STATUS_LABELS: Record<PasswordResetStatus, string> = {
  pending: "待处理",
  approved: "已批准",
  rejected: "已驳回",
};

export const PASSWORD_RESET_STATUS_BADGE: Record<PasswordResetStatus, string> = {
  pending: "badge-warning",
  approved: "badge-success",
  rejected: "badge-danger",
};
