/** 全站弹窗公告（ADR-0042）。字段与后端 announcements/serializers.py 一一对应。 */

export type AnnouncementAudience = "all" | "registered" | "verified" | "admin";

/** 空串 = 没有文档（只有正文）。 */
export type AnnouncementDocumentKind = "" | "pdf" | "docx";

export interface Announcement {
  id: number;
  title: string;
  /** 纯文本正文（弹窗顶部说明，可留空）。 */
  summary: string;
  audience: AnnouncementAudience;
  audience_label: string;
  has_document: boolean;
  document_kind: AnnouncementDocumentKind;
  document_name: string;
  /** 字节。 */
  document_size: number;
  /** 鉴权后的原件地址（/announcements/<id>/file/）；无文档时 null。 */
  file_url: string | null;
  published_at: string | null;
  expires_at: string | null;
  /** 当前用户已读时间；未读 / 匿名时为 null。 */
  read_at: string | null;
  created_at: string;
}

export const AUDIENCE_LABELS: Record<AnnouncementAudience, string> = {
  all: "全站",
  registered: "注册用户",
  verified: "认证用户",
  admin: "管理员",
};

export function formatDocumentSize(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatPublishedAt(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}
