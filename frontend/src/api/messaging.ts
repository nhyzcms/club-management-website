import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type {
  Banner,
  Comment,
  CommentHost,
  CommentThread,
  Conversation,
  DirectMessage,
  MuteStatus,
  Notification,
  NotificationPreferences,
  SubscriptionUpdate,
  ThreadStatus,
  UserMute,
} from "../types/messaging";
import { hostQuery } from "../types/messaging";

const request = createRequest("/messaging");

export const messagingApi = {
  // ---- 评论区 ----
  getThread: (host: CommentHost) => {
    const qs = new URLSearchParams(hostQuery(host)).toString();
    return request(`/threads/?${qs}`) as Promise<CommentThread>;
  },
  patchThread: (id: number, status: ThreadStatus) =>
    request(`/threads/${id}/`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }) as Promise<CommentThread>,

  listComments: (threadId: number, page = 1) =>
    request(`/comments/?thread=${threadId}&page=${page}`) as Promise<Paginated<Comment>>,
  postComment: (thread: number, content: string, parent?: number | null) =>
    request("/comments/", {
      method: "POST",
      body: JSON.stringify(parent ? { thread, content, parent } : { thread, content }),
    }) as Promise<Comment>,
  retractComment: (id: number) =>
    request(`/comments/${id}/retract/`, { method: "POST" }) as Promise<Comment>,
  deleteComment: (id: number) =>
    request(`/comments/${id}/delete/`, { method: "POST" }) as Promise<Comment>,

  /** 创建/编辑宿主后对齐评论区状态（默认开放；无权限或尚未建区时静默）。 */
  applyHostThreadStatus: async (host: CommentHost, status: ThreadStatus) => {
    try {
      const thread = await messagingApi.getThread(host);
      if (thread.status !== status) await messagingApi.patchThread(thread.id, status);
    } catch {
      /* 评论区尚未建好，或当前用户不能改状态 */
    }
  },

  // ---- 私信 ----
  listConversations: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/conversations/${qs}`) as Promise<Paginated<Conversation>>;
  },
  unreadCount: () => request(`/conversations/unread_count/`) as Promise<{ total: number }>,
  getConversation: (id: number) =>
    request(`/conversations/${id}/`) as Promise<Conversation>,
  getMessages: (conversationId: number, page = 1) =>
    request(`/conversations/messages/?conversation_id=${conversationId}&page=${page}`) as Promise<Paginated<DirectMessage>>,
  sendMessage: (conversationId: number, content: string) =>
    request(`/conversations/${conversationId}/send_message/`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }) as Promise<DirectMessage>,
  retractMessage: (conversationId: number, messageId: number) =>
    request(`/conversations/${conversationId}/retract_message/`, {
      method: "POST",
      body: JSON.stringify({ message_id: messageId }),
    }) as Promise<DirectMessage>,
  markRead: (conversationId: number) =>
    request(`/conversations/${conversationId}/mark_read/`, { method: "POST" }),
  startPrivate: (userId: number) =>
    request("/conversations/start_private/", {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }) as Promise<Conversation>,

  // ---- 通知 ----
  listNotifications: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/notifications/${qs}`) as Promise<Paginated<Notification>>;
  },
  notificationUnreadCount: () =>
    request(`/notifications/unread_count/`) as Promise<{ total: number }>,
  markNotificationRead: (id: number) =>
    request(`/notifications/${id}/mark_read/`, { method: "POST" }) as Promise<Notification>,
  markAllNotificationsRead: () =>
    request(`/notifications/mark_read/`, { method: "POST" }),

  // ---- 全站禁言 ----
  myMute: () => request(`/mutes/me/`) as Promise<MuteStatus>,
  muteUser: (userId: number, data?: { reason?: string; ends_at?: string | null }) =>
    request("/mutes/", {
      method: "POST",
      body: JSON.stringify({
        user_id: userId,
        reason: data?.reason || "",
        ...(data?.ends_at ? { ends_at: data.ends_at } : {}),
      }),
    }) as Promise<UserMute>,
  liftMute: (userId: number) =>
    request("/mutes/lift/", {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }) as Promise<UserMute>,

  // ---- 横幅公告 ----
  currentBanner: () => request(`/banners/current/`) as Promise<Banner | null>,

  // ---- 订阅偏好（源 × 通道） ----
  getNotificationPreferences: () =>
    request(`/notification-preferences/`) as Promise<NotificationPreferences>,
  updateNotificationPreferences: (updates: SubscriptionUpdate[]) =>
    request(`/notification-preferences/`, {
      method: "PATCH",
      body: JSON.stringify({ updates }),
    }) as Promise<NotificationPreferences>,
};
