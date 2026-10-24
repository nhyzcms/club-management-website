import { feedbackApi } from "../api/feedback";
import { identityReviewsApi } from "../api/identityReviews";
import { passwordResetApi } from "../api/passwordReset";
import { reportsApi } from "../api/reports";
import { reviewsApi } from "../api/reviews";
import type { FeedbackListItem, FeedbackStatus } from "../types/feedback";
import type { IdentityReviewItem, IdentityReviewStatus } from "../types/identityReviews";
import type { PasswordResetRequestItem, PasswordResetStatus } from "../types/passwordReset";
import type { ReportCase, ReportStatus } from "../types/reports";
import type { ReviewItem, ReviewStatus, ReviewTargetType } from "../types/reviews";
import { TARGET_TYPE_LABELS } from "../types/reviews";

/**
 * 审核台「分桌」的共用逻辑（桌面 / 手机两套 UI 共用一套取数规则）。
 *
 * 背景：审核台有四类队列（身份认证、内容发布、意见反馈、举报案），每类队列
 * 的筛选参数与分页信封都不同。桌面页原先把这些取数函数写在页面里，手机版
 * 需要完全一致的行为（尤其「跳过本轮已浏览条目」与「跨页找下一条」），
 * 因此抽到这里，避免两份实现逐渐漂移。
 */

export type DeskKind =
  | "identity"
  | ReviewTargetType
  | "feedback"
  | "reports"
  | "passwordReset";

export const CONTENT_KINDS: ReviewTargetType[] = ["news", "activity", "tutorial"];

export interface DeskPermissions {
  /** 内容发布审核（新闻 / 活动 / 教程） */
  canContent?: boolean;
  /** 身份认证审核 */
  canIdentity?: boolean;
  /** 意见反馈处理 */
  canFeedback?: boolean;
  /** 举报案处理 */
  canReports?: boolean;
  /** 密码重置审批（忘记密码 → 管理员手动重置） */
  canPasswordReset?: boolean;
}

export interface DeskTab {
  kind: DeskKind;
  label: string;
}

/**
 * 当前用户可见的「桌」清单：顺序固定为
 * 身份 → 密码重置 → 新闻 → 活动 → 教程 → 意见反馈 → 举报案。
 * 没有任何权限时返回空数组（调用方据此显示无权限提示）。
 */
export function deskTabs(p: DeskPermissions): DeskTab[] {
  const tabs: DeskTab[] = [];
  if (p.canIdentity) tabs.push({ kind: "identity", label: "身份" });
  if (p.canPasswordReset) tabs.push({ kind: "passwordReset", label: "密码重置" });
  if (p.canContent) {
    for (const kind of CONTENT_KINDS) {
      tabs.push({ kind, label: TARGET_TYPE_LABELS[kind] });
    }
  }
  if (p.canFeedback) tabs.push({ kind: "feedback", label: "意见反馈" });
  if (p.canReports) tabs.push({ kind: "reports", label: "举报案" });
  return tabs;
}

async function firstOf<T extends { id: number }>(
  fetchPage: (page: number) => Promise<{ results: T[]; next: string | null }>,
  excludeId?: number,
  skip?: Set<number>,
): Promise<T | null> {
  let page = 1;
  for (;;) {
    const data = await fetchPage(page);
    const hit = (data.results || []).find(
      (row) => row.id !== excludeId && !(skip && skip.has(row.id)),
    );
    if (hit) return hit;
    if (!data.next) return null;
    page += 1;
  }
}

export async function firstIdentity(
  status: IdentityReviewStatus,
  excludeId?: number,
  skip?: Set<number>,
) {
  return firstOf(
    (page) => identityReviewsApi.list({ status, page: String(page) }),
    excludeId,
    skip,
  ) as Promise<IdentityReviewItem | null>;
}

export async function firstPasswordReset(
  status: PasswordResetStatus,
  excludeId?: number,
  skip?: Set<number>,
) {
  return firstOf(
    (page) => passwordResetApi.list({ status, page: String(page) }),
    excludeId,
    skip,
  ) as Promise<PasswordResetRequestItem | null>;
}

export async function firstContent(
  type: ReviewTargetType,
  status: ReviewStatus | "",
  excludeId?: number,
  skip?: Set<number>,
) {
  return firstOf(
    async (page) => {
      const params: Record<string, string> = { ordering: "created_at", page: String(page) };
      if (status) params.status = status;
      const data = await reviewsApi.list(params);
      return {
        results: (data.results || []).filter((row) => row.target_type === type),
        next: data.next,
      };
    },
    excludeId,
    skip,
  ) as Promise<ReviewItem | null>;
}

export async function firstFeedback(
  status: FeedbackStatus | "",
  excludeId?: number,
  skip?: Set<number>,
) {
  return firstOf(
    (page) => {
      const params: Record<string, string> = { ordering: "created_at", page: String(page) };
      if (status) params.status = status;
      return feedbackApi.list(params);
    },
    excludeId,
    skip,
  ) as Promise<FeedbackListItem | null>;
}

export async function firstReport(
  status: ReportStatus | "",
  excludeId?: number,
  skip?: Set<number>,
) {
  return firstOf(
    (page) => {
      const params: Record<string, string> = { ordering: "created_at", page: String(page) };
      if (status) params.status = status;
      return reportsApi.list(params);
    },
    excludeId,
    skip,
  ) as Promise<ReportCase | null>;
}
