import type { ThreadStatus } from "./messaging";

export type { Conversation, DirectMessage as Message } from "./messaging";

export interface TaskUser {
  id: number;
  username: string;
  email: string;
  nickname: string;
  avatar: string | null;
  /** 已注销账号（ADR-0025）：后端把 username/avatar 置空、nickname 换成「该用户已注销」。 */
  is_deleted?: boolean;
}

export interface Tag {
  id: number;
  name: string;
  color: string;
  task_count?: number;
}

export interface Attachment {
  id: number;
  file_url: string;
  file_type: "image" | "video" | "document" | "archive" | "other";
  file_name: string;
  file_size: number;
  uploaded_by: TaskUser;
  uploaded_at: string;
}

export interface TaskClaimRequest {
  id: number;
  task: number;
  claimant: TaskUser;
  status: "pending" | "approved" | "rejected";
  reason: string;
  reviewed_by: TaskUser | null;
  reviewed_at: string | null;
  created_at: string;
}

export type TaskStatus = "pending" | "in_progress" | "reviewing" | "review" | "completed" | "cancelled";
export type TaskPriority = "low" | "medium" | "high" | "urgent";

// 任务详情里后端给出的「此刻该用户可执行的动作」标识，与 tasks 生命周期模块
// （tasks/lifecycle.py）的动作常量一一对应。前端据此渲染按钮，不再本地推状态机（#6/#15）。
export type TaskAction =
  | "claim"
  | "approve_claim"
  | "reject_claim"
  | "complete"
  | "approve_completion"
  | "reject_completion"
  | "cancel"
  | "assign";

export interface TaskListItem {
  id: number;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  creator: TaskUser;
  assignee: TaskUser | null;
  tags: Tag[];
  completed_at: string | null;
  reject_reason: string;
  attachment_count: number;
  created_at: string;
  updated_at: string;
}

export interface TaskDetail {
  id: number;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  creator: TaskUser;
  assignee: TaskUser | null;
  collaborators: TaskUser[];
  tags: Tag[];
  attachments: Attachment[];
  claim_requests: TaskClaimRequest[];
  available_actions: TaskAction[];
  completed_at: string | null;
  reject_reason: string;
  created_at: string;
  updated_at: string;
}

export interface TaskFormData {
  title: string;
  description: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  assignee_id?: number | null;
  collaborator_ids?: number[];
  tag_ids?: number[];
  comment_thread_status?: ThreadStatus;
}

export const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: "待处理",
  in_progress: "进行中",
  reviewing: "待验收",
  review: "审核中",
  completed: "已完成",
  cancelled: "已取消",
};

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  low: "低",
  medium: "中",
  high: "高",
  urgent: "紧急",
};

export const PRIORITY_COLORS: Record<TaskPriority, string> = {
  low: "#6b7280",
  medium: "#3b82f6",
  high: "#f59e0b",
  urgent: "#ef4444",
};

export const STATUS_COLORS: Record<TaskStatus, string> = {
  pending: "#6b7280",
  in_progress: "#3b82f6",
  reviewing: "#8b5cf6",
  review: "#f59e0b",
  completed: "#10b981",
  cancelled: "#9ca3af",
};

// cobalt 徽章/圆点类（用于详情页；列表页可后续迁移）
export const STATUS_BADGE_CLASS: Record<TaskStatus, string> = {
  pending: "badge-neutral",
  in_progress: "badge-brand",
  reviewing: "badge-warning",
  review: "badge-brand",
  completed: "badge-success",
  cancelled: "badge-neutral",
};

export const PRIORITY_DOT_CLASS: Record<TaskPriority, string> = {
  low: "is-low",
  medium: "is-medium",
  high: "is-high",
  urgent: "is-urgent",
};
