/**
 * 明信片互寄 API（后端 events/modules/postcard/urls.py，挂在 /events/postcard/ 下）。
 *
 * 用户侧端点全部 AllowAny：归属靠 ncdid Cookie + 指纹 + 登录用户三轨，
 * 写操作另需 6 位登记码（能力凭证，URL 一段）。照片走独立鉴权视图，
 * <img> 标签带 query 凭证（Cookie 自动随行）。
 */
import { createRequest } from "./shared";

const request = createRequest("/events/postcard");

export type PostcardPhase =
  | "not_started"
  | "registering"
  | "shipped"
  | "distributing"
  | "ended";

export interface PostcardGradeOption {
  value: string; // g1 / g2 / g3（登记接口的 grade 键）
  label: string; // 高一 / 高二 / 高三
}

export interface PostcardSchool {
  region: string;
  name: string;
}

export interface PostcardProgressNode {
  key: string;
  label: string;
  time: string | null;
  reached: boolean;
}

export interface PostcardPortal {
  phase: PostcardPhase;
  phase_label: string;
  can_register: boolean;
  is_admin: boolean;
  sample_ready: boolean;
  event: {
    id: number;
    title: string;
    summary: string;
    start_at: string;
    end_at: string | null;
  } | null;
  progress: PostcardProgressNode[];
  grades: PostcardGradeOption[];
  classes: number[];
  regions: string[];
  schools: PostcardSchool[];
  announcement_body: string;
  announcement_pdf: boolean;
}

export interface PostcardPhotoRef {
  id: number;
  side: "front" | "back";
}

export interface PostcardItemSummary {
  id: number;
  barcode: string;
  status: string;
  status_label: string;
  review_state: string | null;
  review_label: string | null;
  /** AI 判不匹配的填写项（「告知用户哪里填错」的数据源） */
  mismatched: string[];
  comment: string;
  photos: PostcardPhotoRef[];
}

export interface PostcardRegistrationSummary {
  /** 单份提交 id（同一登记码可能对应多份提交）。 */
  id: number;
  /** 未达到发放条件时是掩码（82****）。 */
  reg_code: string;
  /** 服务端权威：这条提交现在是否该亮码。 */
  code_granted: boolean;
  /** 轮询凭证（仅 /my/ 列表下发；审核中不暴露 6 位码）。 */
  access_token?: string;
  sender_name: string;
  grade: string;
  grade_label: string;
  class_no: number;
  dest_region: string;
  dest_school: string;
  status: string;
  status_label: string;
  created_at: string;
  updated_at: string;
  items: PostcardItemSummary[];
}

export interface RegisterResult {
  /** 未达发放条件时为 null（审核中 / 判不匹配）。 */
  reg_code: string | null;
  code_granted: boolean;
  /** 审核中的轮询凭证：拉状态、申请人工复核、清失败照片。 */
  access_token: string;
  message: string;
  registration: PostcardRegistrationSummary;
  review: { state: string; hint: string };
}

export const postcardApi = {
  /** 独立页一站式状态（阶段 / 公告 / 进度 / 表单元数据）。 */
  portal: () => request<PostcardPortal>("/portal/"),

  /** 登记提交（multipart：表单字段 + items JSON + photo_<i>_front/back）。 */
  register: (data: FormData) =>
    request<RegisterResult>("/register/", { method: "POST", body: data }),

  /** 历史登记记录（三轨归属自动匹配）。 */
  my: (fingerprint: string) =>
    request<{ results: PostcardRegistrationSummary[] }>(
      `/my/?fingerprint=${encodeURIComponent(fingerprint)}`,
    ),

  detail: (regCode: string, fingerprint: string, submissionId?: number) =>
    request<PostcardRegistrationSummary>(
      `/my/${encodeURIComponent(regCode)}/?fingerprint=${encodeURIComponent(fingerprint)}`
        + (submissionId ? `&id=${submissionId}` : ""),
    ),

  /** 审核中的轮询（凭证不含 6 位码，未通过时也不泄露能力凭证）。 */
  statusByToken: (token: string) =>
    request<PostcardRegistrationSummary>(`/my/token/${encodeURIComponent(token)}/`),

  /**
   * 用户侧查询（2026-11-08）：q = 6 位登记码 → 完整摘要（能力凭证，可直接改）；
   * q = 寄出人姓名 → 掩码摘要（reg_code 形如 82****、无照片，需完整码才能改）。
   */
  lookup: (q: string) =>
    request<{ kind: "code" | "name"; results: PostcardRegistrationSummary[] }>(
      "/lookup/",
      { method: "POST", body: JSON.stringify({ q }) },
    ),

  /** 修改自己的登记（仅寄出人信息；条码与照片不可改——实物已印好）。 */
  update: (
    regCode: string,
    patch: Partial<Pick<PostcardRegistrationSummary, "sender_name" | "grade" | "class_no" | "dest_region" | "dest_school">>,
    fingerprint: string,
    submissionId?: number,
  ) =>
    request<PostcardRegistrationSummary>(
      `/my/${encodeURIComponent(regCode)}/` + (submissionId ? `?id=${submissionId}` : ""),
      { method: "PATCH", body: JSON.stringify({ ...patch, fingerprint }) },
    ),

  /**
   * 取消登记（不可恢复）：scope="one" 取消单份提交；scope="all" 取消该码下全部提交。
   * 整批取消前前端必须二次确认（重新输入 6 位登记码）。
   */
  cancel: (
    regCode: string,
    fingerprint: string,
    scope: "one" | "all" = "one",
    submissionId?: number,
  ) =>
    request<PostcardRegistrationSummary>(
      `/my/${encodeURIComponent(regCode)}/` + (submissionId ? `?id=${submissionId}` : ""),
      { method: "POST", body: JSON.stringify({ fingerprint, scope }) },
    ),

  /** AI 判不匹配后申请人工复核。 */
  requestReview: (regCode: string, fingerprint: string) =>
    request<{ message: string; count: number }>(
      `/my/${encodeURIComponent(regCode)}/review-request/`,
      { method: "POST", body: JSON.stringify({ fingerprint }) },
    ),

  /** 审核中（还没拿到 6 位码）申请人工复核：走轮询凭证。 */
  requestReviewByToken: (token: string) =>
    request<{ message: string; count: number }>(
      `/my/token/${encodeURIComponent(token)}/review-request/`,
      { method: "POST", body: "{}" },
    ),

  /** 建议箱。 */
  suggest: (content: string, contact: string, turnstileToken: string) =>
    request<{ message: string }>("/suggestions/", {
      method: "POST",
      body: JSON.stringify({
        content,
        ...(contact ? { contact } : {}),
        ...(turnstileToken ? { turnstile_token: turnstileToken } : {}),
      }),
    }),

  /** 鉴权照片 URL（<img> 用；Cookie 自动随行 + 登记码/指纹 query 凭证）。 */
  photoUrl: (photoId: number, regCode: string, fingerprint: string) =>
    `/events/postcard/photo/${photoId}/?reg_code=${encodeURIComponent(regCode)}&fingerprint=${encodeURIComponent(fingerprint)}`,

  /** 公告 PDF（CSP:sandbox + nosniff，新标签页打开由浏览器 PDF 查看器渲染）。 */
  announcementPdfUrl: () => "/events/postcard/announcement-pdf/",
};

/**
 * 关标签页清理失败照片（sendBeacon）。
 *
 * 审核失败时登记码尚未发放（服务端只给掩码），所以清理凭证是登记时下发的
 * ``access_token``；服务端 24h TTL 仍是兜底。必须以 application/json Blob
 * 发送（后端该端点豁免 CSRF，凭证在 URL 里）。
 */
export function purgePhotosBeacon(token: string): void {
  try {
    const blob = new Blob(["{}"], { type: "application/json" });
    navigator.sendBeacon(
      `/events/postcard/my/token/${encodeURIComponent(token)}/purge-photos/`,
      blob,
    );
  } catch {
    /* 发不出就算了：服务端 24h TTL 兜底清理 */
  }
}
