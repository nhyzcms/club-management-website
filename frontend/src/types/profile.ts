export type RoleVariant = "visitor" | "user" | "admin" | "superadmin";

export interface UserProfileData {
  /** 已注销账号的墓碑响应（ADR-0025）：只为 true 时下方字段可能为空。 */
  deleted?: boolean;
  user: { id: number; username: string; date_joined: string; email?: string };
  profile: {
    avatar: string | null;
    nickname: string;
    bio: string;
    birthday?: string | null;
    gender?: string;
  };
  role: { label: string; variant: RoleVariant };
  viewer: { is_owner: boolean; is_admin: boolean };
  permissions?: Record<string, boolean>;
  groups?: string[];
}

export type ContentType = "news" | "feedback" | "tasks" | "activities" | "tutorials";

export interface ContentItem {
  id: number;
  title: string;
  created_at?: string;
  published_at?: string;
  cover_image?: string | null;
  is_published?: boolean;
  review_status?: string | null;
  category?: string;
  status?: string;
  priority?: string;
  type?: string;
}

/** 角色 variant → 徽章 CSS 类（配色在 styles/profile.css） */
export const ROLE_BADGE: Record<RoleVariant, string> = {
  visitor: "badge-role-visitor",
  user: "badge-role-user",
  admin: "badge-role-admin",
  superadmin: "badge-role-superadmin",
};

/** 身份枚举（与后端 Profile.IDENTITY_CHOICES 对齐）：注册页 / 人工审批共用。 */
export const IDENTITY_OPTIONS: { value: string; label: string }[] = [
  { value: "student", label: "在校生" },
  { value: "external", label: "外校生" },
  { value: "graduate", label: "毕业生" },
  { value: "parent", label: "家长" },
  { value: "teacher", label: "教师" },
];

/** 需要登记「校牌号」的身份（与后端 Profile.CARD_NO_IDENTITIES 对齐）：在校生 / 毕业生。 */
export const CARD_NO_IDENTITIES: string[] = ["student", "graduate"];
