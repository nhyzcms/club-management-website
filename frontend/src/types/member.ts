/** 社员身份（Part A / ADR-0025）类型与常量。契约以 accounts 测试钉死，防漂移。 */

export interface MemberIdentityBound {
  id: number;
  name: string;
  cohort: number;
  group: string;
  code: string;
  status: string;
  bound_at: string | null;
}

export interface MemberIdentityCandidate {
  id: number;
  name: string;
  cohort: number;
  group: string;
}

export interface MemberIdentityStatus {
  enabled: boolean;
  bound: MemberIdentityBound | null;
  candidates: MemberIdentityCandidate[];
}

/** 在册状态 → 文案（与后端 MemberIdentity.STATUS_* 对齐）。 */
export const MEMBER_STATUS_LABELS: Record<string, string> = {
  active: "在册",
  graduated: "已毕业",
  left: "已退社",
};
