import type { TaskUser } from "./tasks";

export type ThreadStatus = "open" | "muted" | "closed";

export type CommentHost =
  | { news: number }
  | { activity: number }
  | { task: number };

export interface CommentThread {
  id: number;
  status: ThreadStatus;
  news: number | null;
  activity: number | null;
  task: number | null;
  can_manage: boolean;
}

export interface Comment {
  id: number;
  thread: number;
  author: TaskUser;
  parent: number | null;
  content: string;
  retracted_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  replies: Comment[];
}

export interface Conversation {
  id: number;
  title: string;
  participants: TaskUser[];
  last_message: DirectMessage | null;
  unread_count: number;
  created_at: string;
  updated_at: string;
}

export interface DirectMessage {
  id: number;
  conversation: number;
  sender: TaskUser;
  content: string;
  mentions: TaskUser[];
  is_read: boolean;
  retracted_at: string | null;
  created_at: string;
  updated_at: string;
}

export type NotificationCategory = "comment" | "review" | "discipline" | "dm";

export interface Notification {
  id: number;
  category: NotificationCategory;
  event: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export interface Banner {
  id: number;
  body: string;
  link: string;
  starts_at: string;
  ends_at: string;
  priority: number;
}

export interface UserMute {
  id: number;
  user: number;
  muted_by: number;
  reason: string;
  starts_at: string;
  ends_at: string | null;
  lifted_at: string | null;
}

export interface MuteStatus {
  muted: boolean;
  mute: UserMute | null;
}

export const THREAD_STATUS_LABELS: Record<ThreadStatus, string> = {
  open: "开放",
  muted: "评论区禁言",
  closed: "彻底关闭",
};

export const NOTIFICATION_CATEGORY_LABELS: Record<NotificationCategory, string> = {
  comment: "评论",
  review: "审核",
  discipline: "纪律",
  dm: "私信",
};

export const NOTIFICATION_EVENT_LABELS: Record<string, string> = {
  comment_replied: "有人回复了你的评论",
  comment_mentioned: "有人在评论中提到了你",
  comment_posted: "有新的评论",
  muted: "你已被全站禁言",
  mute_lifted: "全站禁言已解除",
  mute_expired: "全站禁言已到期",
  approved: "内容已通过审核",
  rejected: "内容未通过审核",
  removed: "内容已下架",
  new_message: "你收到一条新私信",
};

export const RETRACT_WINDOW_MS = 3 * 60 * 1000;

export function withinRetractWindow(createdAt: string, now = Date.now()): boolean {
  const t = new Date(createdAt).getTime();
  return Number.isFinite(t) && now - t < RETRACT_WINDOW_MS;
}

export function hostQuery(host: CommentHost): Record<string, string> {
  if ("news" in host) return { news: String(host.news) };
  if ("activity" in host) return { activity: String(host.activity) };
  return { task: String(host.task) };
}

export function notificationHref(n: Notification): string | null {
  const p = n.payload || {};
  const url = p.url;
  if (typeof url === "string" && url) {
    if (url.startsWith("http://") || url.startsWith("https://")) return url;
    return url.startsWith("/") ? url : `/${url}`;
  }
  if (typeof p.news_id === "number") return `/news/${p.news_id}`;
  if (typeof p.activity_id === "number") return `/activity/${p.activity_id}`;
  if (typeof p.task_id === "number") return `/tasks/${p.task_id}`;
  return null;
}

/**
 * 通知标题：事件文案 → 分类文案 → 兜底。
 *
 * 私信是**按会话聚合**的未读通知（连发多条只提示一次），载荷里的 `count` 是
 * 累计条数，>1 时直接报条数，比「你收到一条新私信」准确。
 */
export function notificationTitle(n: Notification): string {
  const payload = n.payload || {};
  const count = payload.count;
  if (n.event === "new_message" && typeof count === "number" && count > 1) {
    return `你收到 ${count} 条新私信`;
  }
  return NOTIFICATION_EVENT_LABELS[n.event]
    || NOTIFICATION_CATEGORY_LABELS[n.category]
    || "通知";
}


// ---- 订阅偏好（源 × 通道） ----
export interface NotificationSourcePref {
  key: string;
  name: string;
  description: string;
  events: { key: string; name: string }[];
  channels: Record<string, boolean>;
}

export interface NotificationChannelInfo {
  key: string;
  name: string;
  description: string;
  available: boolean;
}

export interface NotificationPreferences {
  sources: NotificationSourcePref[];
  channels: NotificationChannelInfo[];
}

export interface SubscriptionUpdate {
  source: string;
  channel: string;
  enabled: boolean;
}
