// 活动（events app）：一段有明确起止的时间窗，参与方式由 module_key 决定。
// 与「互动」（activities）的分野：互动是星形（中心→成员），活动允许参与者之间发生关系。

export type EventStatus = "draft" | "scheduled" | "active" | "ended" | "archived";
export type EventVisibility = "public" | "members";

export interface EventOrganizer {
  id: number;
  username: string;
  nickname?: string;
  avatar?: string;
}

export interface Event {
  id: number;
  title: string;
  summary: string;
  body: string;
  organizer: EventOrganizer | null;
  start_at: string;
  end_at: string | null;
  status: EventStatus;
  status_label: string;
  visibility: EventVisibility;
  visibility_label: string;
  module_key: string;
  created_at: string;
  updated_at: string;
}

export interface EventFormData {
  title: string;
  summary?: string;
  body?: string;
  start_at: string;
  end_at?: string | null;
  visibility?: EventVisibility;
  module_key?: string;
}

/** 状态徽章：tone 映射到既有 .badge 配色（与活动/新闻的徽章体系一致）。 */
export const EVENT_STATUS_META: Record<EventStatus, { label: string; tone: string }> = {
  draft: { label: "草稿", tone: "muted" },
  scheduled: { label: "待开始", tone: "info" },
  active: { label: "进行中", tone: "success" },
  ended: { label: "已结束", tone: "muted" },
  archived: { label: "已归档", tone: "muted" },
};
