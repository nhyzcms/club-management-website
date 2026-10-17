import type { TaskUser, Attachment } from "./tasks";
import type { ThreadStatus } from "./messaging";

// 活动（ADR 0007 / 0011）：众议 / 征集 / 展示 / 调研。独立于申报（反馈）。

export type ActivityType = "deliberation" | "collection" | "exhibition" | "survey";
export type SurveyAudience = "public" | "members";
export type ActivityStatus =
  | "scheduled" // 排期：start_at 之前，待开始
  | "open" // 众议：投票中
  | "closed" // 众议：已截止结算
  | "collecting" // 征集：收件中
  | "reviewing" // 征集：复审中
  | "archived"; // 征集：已归档
export type ReviewStatus = "pending" | "accepted" | "rejected";

export interface ActivityListItem {
  id: number;
  type: ActivityType;
  status: ActivityStatus;
  title: string;
  creator: TaskUser | null;
  audience?: SurveyAudience; // 受众：调研=作答资格，众议/展示=投票资格（公开时游客可投）
  review_status?: "pending" | "approved" | "rejected" | "removed" | null;
  owed?: "vote" | "submit" | null;
  start_at: string | null;
  end_at: string | null;
  is_permanent: boolean; // 长期有效：不设截止，仅能由发起人/管理员手动终结
  created_at: string;
  updated_at: string;
}

export interface VoteOption {
  id: number;
  text: string;
  order: number;
  vote_count: number;
}

export interface Ballot {
  id: number;
  voter: TaskUser | null; // 公开受众的游客票（无账号）为 null
  option_ids: number[];
  created_at: string;
}

export interface Submission {
  id: number;
  submitter: TaskUser;
  files: Attachment[];
  review_status: ReviewStatus;
  review_comment: string;
  reviewed_at: string | null;
  created_at: string;
}

export interface Exhibit {
  id: number;
  title: string;
  files: Attachment[];
  vote_option_id: number | null; // 每展品一个投票选项（创建时绑定）；null 则不可投票
  vote_count: number;
  like_count: number;
  dislike_count: number;
  my_rating: "like" | "dislike" | null;
  created_at: string;
}

export interface ActivityDetail {
  id: number;
  type: ActivityType;
  status: ActivityStatus;
  title: string;
  body: string;
  creator: TaskUser | null;
  review_status?: "pending" | "approved" | "rejected" | "removed" | null;
  review_comment?: string;
  owed?: "vote" | "submit" | null;
  start_at: string | null;
  end_at: string | null;
  is_permanent: boolean; // 长期有效：不设截止，仅能由发起人/管理员手动终结
  // 众议
  max_choices_per_voter: number;
  is_secret_ballot: boolean;
  options: VoteOption[];
  ballots: Ballot[] | null; // 秘密投票下非超管为 null
  my_selections: number[] | null;
  total_ballots: number | null;
  // 征集
  allowed_extensions: string;
  max_file_size: number | null;
  max_files_per_submission: number;
  max_submissions: number | null;
  review_enabled: boolean;
  my_submission: Submission | null;
  submissions: Submission[] | null; // 复审者见全部；其余仅录用（公开展示）
  // 展示
  exhibits: Exhibit[] | null;
  voting_enabled: boolean; // 展示是否启用活动级投票；false=纯陈列（仅展品+赞/踩）
  // 受众（调研=作答资格；众议/展示=投票资格）
  audience: SurveyAudience;
  schema: Record<string, unknown>;
  my_response: Record<string, unknown> | null; // 当前身份（登录用户或访客设备）的作答；未答为 null
  response_count: number | null; // 作答总数（不作答列表；非调研为 null）
  schema_editable: boolean; // 调研 Schema 可否改（生命周期；非调研为 false）
  created_at: string;
  updated_at: string;
}

// ---- 问卷作答查看 ----
/** 检索命中字段（?q= 时后端回传，用于提示「哪道题命中了」）。 */
export interface SurveyResponseMatch {
  name: string;
  title: string;
  snippet: string;
}

export interface SurveyResponseRow {
  id: number;
  user_label: string;
  answers: Record<string, unknown>;
  submitted_at: string;
  matches: SurveyResponseMatch[]; // 未检索时为空数组
}

export interface SurveyResponsesPayload {
  schema: Record<string, unknown>;
  is_manager: boolean;
  total: number; // 未过滤的可见份数（检索时用于「匹配 N / 共 M」）
  query: string; // 已生效的检索词（空串 = 未检索）
  results: SurveyResponseRow[];
}

// ---- 创建表单 ----
export interface DeliberationFormData {
  type: "deliberation";
  title: string;
  body: string;
  max_choices_per_voter: number;
  is_secret_ballot: boolean;
  audience: SurveyAudience;
  start_at?: string;
  end_at?: string | null;
  is_permanent?: boolean;
  option_texts: string[];
  comment_thread_status?: ThreadStatus;
}

export interface CollectionFormData {
  type: "collection";
  title: string;
  body: string;
  allowed_extensions: string;
  max_file_size: number | null;
  max_files_per_submission: number;
  max_submissions: number | null;
  review_enabled: boolean;
  start_at?: string;
  end_at?: string | null;
  is_permanent?: boolean;
  comment_thread_status?: ThreadStatus;
}

export interface ExhibitionFormData {
  type: "exhibition";
  title: string;
  body: string;
  voting_enabled: boolean;
  max_choices_per_voter: number; // 启用投票时有意义
  is_secret_ballot: boolean;
  audience: SurveyAudience;
  start_at?: string;
  end_at?: string | null;
  is_permanent?: boolean;
  comment_thread_status?: ThreadStatus;
}

export interface SurveyFormData {
  type: "survey";
  title: string;
  body: string;
  audience: SurveyAudience;
  start_at?: string;
  end_at?: string | null;
  is_permanent?: boolean;
  comment_thread_status?: ThreadStatus;
}

// 众议/征集/展示/调研均走 JSON 创建标量(展品改在详情页 add_exhibit 录入；调研问卷改在 survey-edit)。
export type ActivityFormData = DeliberationFormData | CollectionFormData | ExhibitionFormData | SurveyFormData;

// ---- 标签 ----
export const ACTIVITY_TYPE_LABELS: Record<ActivityType, string> = {
  deliberation: "众议",
  collection: "征集",
  exhibition: "展示",
  survey: "调研",
};

export const AUDIENCE_LABELS: Record<SurveyAudience, string> = {
  public: "公开",
  members: "仅成员",
};

// 活动类型勋章：emoji + 配色徽章（替换纯文字 type-tag）
export const ACTIVITY_TYPE_META: Record<ActivityType, { label: string; emoji: string; medal: string }> = {
  deliberation: { label: "众议", emoji: "🗳", medal: "medal-vote" },
  collection: { label: "征集", emoji: "📥", medal: "medal-collect" },
  exhibition: { label: "展示", emoji: "🖼", medal: "medal-exhibit" },
  survey: { label: "调研", emoji: "📋", medal: "medal-survey" },
};

export const ACTIVITY_STATUS_LABELS: Record<ActivityStatus, string> = {
  scheduled: "待开始",
  open: "投票中",
  closed: "已结束",
  collecting: "收件中",
  reviewing: "复审中",
  archived: "已归档",
};

// ---- 阶段勋章（替换纯文字状态徽章）：emoji + 配色 pill ----
// 类型勋章(ACTIVITY_TYPE_META)回答"这是什么活动"，阶段勋章回答"现在到哪一步了"。
// open 阶段按类型区分（众议=投票中 / 展示=展示中 / 调研=征答中）——展示/调研在 open 态不再误显示"投票中"。
export const ACTIVITY_PHASE_EMOJI: Record<ActivityStatus, string> = {
  scheduled: "⏳",
  open: "⚖️",
  collecting: "📨",
  reviewing: "🔍",
  closed: "🏁",
  archived: "📦",
};

const PHASE_CLASS: Record<ActivityStatus, string> = {
  scheduled: "medal-phase-amber",
  open: "medal-phase-brand",
  collecting: "medal-phase-brand",
  reviewing: "medal-phase-amber",
  closed: "medal-phase-neutral",
  archived: "medal-phase-neutral",
};

// open 阶段按类型差异化：展示=展示中(紫)，调研=征答中，众议=投票中(brand)；征集不会进入 open（占位）。
const OPEN_PHASE: Record<ActivityType, { label: string; medalClass: string }> = {
  deliberation: { label: "投票中", medalClass: "medal-phase-brand" },
  collection: { label: "投票中", medalClass: "medal-phase-brand" },
  exhibition: { label: "展示中", medalClass: "medal-phase-exhibit" },
  survey: { label: "征答中", medalClass: "medal-phase-brand" },
};

export interface ActivityPhaseMeta {
  emoji: string;
  label: string;
  medalClass: string;
}

export function activityPhase(type: ActivityType, status: ActivityStatus): ActivityPhaseMeta {
  if (status === "open") {
    const o = OPEN_PHASE[type];
    return { emoji: ACTIVITY_PHASE_EMOJI.open, label: o.label, medalClass: o.medalClass };
  }
  return {
    emoji: ACTIVITY_PHASE_EMOJI[status],
    label: ACTIVITY_STATUS_LABELS[status],
    medalClass: PHASE_CLASS[status],
  };
}

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  pending: "待复审",
  accepted: "录用",
  rejected: "退稿",
};

export const REVIEW_STATUS_BADGE_CLASS: Record<ReviewStatus, string> = {
  pending: "badge-warning",
  accepted: "badge-success",
  rejected: "badge-neutral",
};
