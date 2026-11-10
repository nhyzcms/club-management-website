import type { ActivityListItem } from "./activities";
import type { TaskListItem, TaskUser, Message } from "./tasks";
import type { Paginated } from "./pagination";

export type InboxKind = "activity" | "task" | "conversation";
export type InboxReason =
  | "vote"
  | "submit"
  | "complete"
  | "approve_completion"
  | "approve_claim"
  | "unread";

export interface InboxConversation {
  id: number;
  conversation_type: string;
  task: number | null;
  title: string;
  participants: TaskUser[];
  last_message: Message | null;
  unread_count: number;
  created_at: string;
  updated_at: string;
}

export interface InboxItem {
  kind: InboxKind;
  reason: InboxReason;
  pinned: boolean;
  updated_at: string;
  end_at: string | null;
  activity: ActivityListItem | null;
  task: TaskListItem | null;
  conversation: InboxConversation | null;
}

export type InboxResponse = Paginated<InboxItem>;

export const INBOX_REASON_LABELS: Record<InboxReason, string> = {
  vote: "待投票",
  submit: "待投稿",
  complete: "待完成/交验收",
  approve_completion: "待验收",
  approve_claim: "待批认领",
  unread: "未读",
};
