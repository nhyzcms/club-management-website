import type { TaskUser, Attachment } from "./tasks";

export type FeedbackStatus = "pending" | "closed";
export type FeedbackCategory = "suggestion" | "complaint" | "other";

export interface FeedbackListItem {
  id: number;
  status: FeedbackStatus;
  title: string;
  creator: TaskUser | null;
  contact: string;
  category: FeedbackCategory;
  close_note: string;
  attachment_count: number;
  created_at: string;
  updated_at: string;
}

export interface FeedbackDetail {
  id: number;
  status: FeedbackStatus;
  title: string;
  description: string;
  category: FeedbackCategory;
  contact: string;
  creator: TaskUser | null;
  closed_by: TaskUser | null;
  closed_at: string | null;
  close_note: string;
  attachments: Attachment[];
  created_at: string;
  updated_at: string;
}

export interface FeedbackFormData {
  title: string;
  description: string;
  category: FeedbackCategory;
  contact?: string;
  disclose_identity?: boolean;
  turnstile_token?: string;
}

export const FEEDBACK_STATUS_LABELS: Record<FeedbackStatus, string> = {
  pending: "待处理",
  closed: "已了结",
};

export const FEEDBACK_STATUS_BADGE: Record<FeedbackStatus, string> = {
  pending: "badge-warning",
  closed: "badge-neutral",
};

export const FEEDBACK_CATEGORY_LABELS: Record<FeedbackCategory, string> = {
  suggestion: "建议",
  complaint: "投诉",
  other: "其他",
};
