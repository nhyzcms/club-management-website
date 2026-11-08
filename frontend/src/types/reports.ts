import type { TaskUser } from "./tasks";

export type ReportStatus = "open" | "dismissed" | "upheld";
export type ReportTargetType = "news" | "activity" | "tutorial" | "comment" | "user";

export interface ReportFiling {
  id: number;
  reporter: TaskUser;
  reason: string;
  created_at: string;
}

export interface ReportCase {
  id: number;
  status: ReportStatus;
  target_type: ReportTargetType | null;
  target_id: number;
  title: string;
  resolved_by: TaskUser | null;
  resolved_at: string | null;
  resolution_comment: string;
  filings: ReportFiling[];
  created_at: string;
  updated_at: string;
}

export const REPORT_STATUS_LABELS: Record<ReportStatus, string> = {
  open: "进行中",
  dismissed: "已驳回",
  upheld: "成立并处置",
};

export const REPORT_STATUS_BADGE: Record<ReportStatus, string> = {
  open: "badge-warning",
  dismissed: "badge-ghost",
  upheld: "badge-success",
};

export const REPORT_TARGET_LABELS: Record<ReportTargetType, string> = {
  news: "新闻",
  activity: "活动",
  tutorial: "教程",
  comment: "评论",
  user: "用户",
};
