export type IdentityReviewStatus = "pending" | "approved" | "rejected";

export interface IdentityProofBrief {
  id: number;
  uploaded_at: string;
  url: string;
}

export interface IdentityReviewItem {
  id: number;
  user_id: number;
  username: string;
  real_name: string;
  identity: string;
  /** 教师身份的所属部门（德育处 / 体育组）；其余身份为空串。 */
  department?: string;
  status: IdentityReviewStatus;
  verified_at: string | null;
  verified_by: { id: number; username: string } | null;
  proofs: IdentityProofBrief[];
}

export const IDENTITY_STATUS_LABELS: Record<IdentityReviewStatus, string> = {
  pending: "待审",
  approved: "已通过",
  rejected: "已驳回",
};

export const IDENTITY_STATUS_BADGE: Record<IdentityReviewStatus, string> = {
  pending: "badge-warning",
  approved: "badge-success",
  rejected: "badge-danger",
};

export const IDENTITY_LABELS: Record<string, string> = {
  student: "在校生",
  external: "外校生",
  graduate: "毕业生",
  parent: "家长",
  teacher: "教师",
};

/** 教师部门标签（与后端 Profile.TEACHER_DEPARTMENT_CHOICES 对齐）。 */
export const TEACHER_DEPARTMENT_LABELS: Record<string, string> = {
  moral: "德育处",
  sports: "体育组",
};

/** 身份标签 + 教师部门（如「教师 · 德育处」）；无部门时只返回身份标签。 */
export function identityWithDepartment(
  item: Pick<IdentityReviewItem, "identity" | "department">,
): string {
  const label = IDENTITY_LABELS[item.identity] || item.identity || "未填写";
  const dept = item.department ? TEACHER_DEPARTMENT_LABELS[item.department] : "";
  return dept ? `${label} · ${dept}` : label;
}
