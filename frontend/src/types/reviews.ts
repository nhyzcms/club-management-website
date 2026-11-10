export type ReviewStatus = "pending" | "approved" | "rejected" | "removed";
export type ReviewTargetType = "news" | "activity" | "tutorial";

export interface ReviewItem {
  id: number;
  status: ReviewStatus;
  comment: string;
  reviewer: { id: number; username: string; nickname: string } | null;
  reviewed_at: string | null;
  target_type: ReviewTargetType | null;
  target_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  pending: "待审",
  approved: "通过",
  rejected: "驳回",
  removed: "下架",
};

export const REVIEW_STATUS_BADGE: Record<ReviewStatus, string> = {
  pending: "badge-warning",
  approved: "badge-success",
  rejected: "badge-danger",
  removed: "badge-ghost",
};

export const TARGET_TYPE_LABELS: Record<string, string> = {
  news: "新闻",
  activity: "活动",
  tutorial: "教程",
};
