import type { ActivityType } from "./activities"; // 活动类型单一事实源（与表单/详情页共用）

export type FeedType = "news" | "activity" | "task";

export type FeedTaskStatus = "pending" | "in_progress" | "reviewing" | "review";
export type FeedTaskPriority = "low" | "medium" | "high" | "urgent";

export interface FeedAssignee {
  id: number;
  username: string;
  nickname: string;
  avatar: string | null;
}

interface FeedItemBase {
  type: FeedType;
  id: number;
  title: string;
  timestamp: string; // ISO8601，排序依据
}

export interface NewsFeedItem extends FeedItemBase {
  type: "news";
  summary: string;
  cover_image_url: string | null;
  cover_thumbnail_url: string | null;
  views: number;
}

export interface ActivityFeedItem extends FeedItemBase {
  type: "activity";
  activity_type: ActivityType;
  status: string;
}

export interface TaskFeedItem extends FeedItemBase {
  type: "task";
  status: FeedTaskStatus;
  priority: FeedTaskPriority;
  assignee: FeedAssignee | null;
}

export type FeedItem = NewsFeedItem | ActivityFeedItem | TaskFeedItem;

export interface FeedResponse {
  featured: NewsFeedItem | null;
  items: FeedItem[];
}

export const FEED_TASK_STATUS_LABEL: Record<FeedTaskStatus, string> = {
  pending: "待处理",
  in_progress: "进行中",
  reviewing: "待验收",
  review: "审核中",
};

export const FEED_TASK_PRIORITY_LABEL: Record<FeedTaskPriority, string> = {
  low: "低",
  medium: "中",
  high: "高",
  urgent: "紧急",
};

// 优先级条形格数（1~3）
export const FEED_TASK_PRIORITY_BARS: Record<FeedTaskPriority, number> = {
  low: 1,
  medium: 2,
  high: 3,
  urgent: 3,
};
