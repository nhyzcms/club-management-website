/**
 * 明信片互寄用户侧纯逻辑（无 React 依赖，单测直接覆盖）。
 *
 * 契约来源：events/modules/postcard/serializers.py（条码 7 位数字、单次 ≤5 张、
 * 重复拒绝）与 photos.py（原始上传 ≤5MB）。前端先拦一道给即时反馈，
 * 服务端校验仍是权威。
 */
import type { PostcardRegistrationSummary, PostcardSchool } from "../../api/postcard";

/** 单次登记最多明信片张数（后端 MAX_ITEMS_PER_REGISTRATION）。 */
export const MAX_ITEMS = 5;
/** 原始照片上限 5MB（后端 MAX_RAW_BYTES）。 */
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
/** 条码号：7 位纯数字（后端 _BARCODE_RE）。 */
export const BARCODE_RE = /^\d{7}$/;

/** 表单里的待登记条目：条码 + 正/反两面照片文件。 */
export interface DraftItem {
  barcode: string;
  front: File | null;
  back: File | null;
}

export type AddBarcodeResult =
  | { ok: true; items: DraftItem[] }
  | { ok: false; reason: string };

/** 扫码 / 手填后把条码加入列表：格式、查重、上限三道闸。 */
export function addBarcode(items: DraftItem[], raw: string): AddBarcodeResult {
  const code = (raw || "").replace(/[\s-]/g, "");
  if (!BARCODE_RE.test(code)) {
    return { ok: false, reason: "条码号须为 7 位数字（明信片上条形码下方的数字）" };
  }
  if (items.some((it) => it.barcode === code)) {
    return { ok: false, reason: `条码 ${code} 已在列表中，一条码对应一份明信片` };
  }
  if (items.length >= MAX_ITEMS) {
    return { ok: false, reason: `单次最多登记 ${MAX_ITEMS} 张明信片，可分多次提交` };
  }
  return { ok: true, items: [...items, { barcode: code, front: null, back: null }] };
}

/** 区内编号比较：有编号的按编号升序在前，无编号的排末尾（老清单兜底），同号按校名。 */
function compareSchool(a: PostcardSchool, b: PostcardSchool): number {
  const an = typeof a.no === "number" ? a.no : null;
  const bn = typeof b.no === "number" ? b.no : null;
  if (an !== bn) {
    if (an === null) return 1;
    if (bn === null) return -1;
    return an - bn;
  }
  return a.name.localeCompare(b.name, "zh-Hans-CN");
}

/** 寄达校排序：区内按编号（「浦东新区1/2/3…」），无编号的排末尾。 */
export function sortSchools(schools: PostcardSchool[]): PostcardSchool[] {
  return [...(schools || [])].sort(compareSchool);
}

/**
 * 寄达校检索：先按区过滤、再按关键词筛（空关键词 = 全区按编号列出）。
 *
 * 关键词命中三种写法：校名片段、纯编号（`12`）、完整编号（`浦东新区12`）；
 * 换区后由调用方清空关键词，避免「上一区的词搜不到新区学校」的错觉。
 */
export function filterSchools(
  schools: PostcardSchool[],
  region: string,
  query: string,
): PostcardSchool[] {
  const list = sortSchools((schools || []).filter((s) => s.region === region));
  const q = (query || "").trim().toLowerCase().replace(/\s+/g, "");
  if (!q) return list;
  const numeric = /^\d+$/.test(q);
  return list.filter((s) => {
    if (s.name.toLowerCase().includes(q)) return true;
    if (typeof s.no !== "number") return false;
    if (q === `${s.region}${s.no}`.toLowerCase()) return true;
    return numeric ? String(s.no) === q : `${s.region}${s.no}`.toLowerCase().includes(q);
  });
}

/** 下拉展示文案：`12 · 某某中学`（无编号时只显示校名）。 */
export function schoolLabel(s: PostcardSchool): string {
  return typeof s.no === "number" ? `${s.no} · ${s.name}` : s.name;
}

export interface RegisterFormValues {
  sender_name: string;
  grade: string;
  class_no: string;
  dest_region: string;
  dest_school: string;
}

/** 提交前整单校验：返回第一条错误文案，全过返回 null。 */
export function validateRegistration(
  values: RegisterFormValues,
  items: DraftItem[],
): string | null {
  if (!values.sender_name.trim()) return "请填写姓名";
  if (!values.grade) return "请选择年级";
  if (!values.class_no) return "请选择班级";
  if (!values.dest_region) return "请选择寄达区";
  if (!values.dest_school) return "请选择寄达校";
  if (items.length === 0) return "请至少添加 1 张明信片（扫码或手动输入条码号）";
  for (let i = 0; i < items.length; i++) {
    if (!BARCODE_RE.test(items[i].barcode)) {
      return `第 ${i + 1} 张明信片的条码号须为 7 位数字`;
    }
    if (!items[i].front) return `第 ${i + 1} 张明信片缺少正面照片`;
    if (!items[i].back) return `第 ${i + 1} 张明信片缺少反面照片`;
  }
  return null;
}

/** 组装登记 multipart（后端 RegisterView 契约：items JSON + photo_<i>_front/back）。 */
export function buildRegisterFormData(
  values: RegisterFormValues,
  items: DraftItem[],
  fingerprint: string,
  turnstileToken: string,
): FormData {
  const fd = new FormData();
  fd.set("sender_name", values.sender_name.trim());
  fd.set("grade", values.grade);
  fd.set("class_no", values.class_no);
  fd.set("dest_region", values.dest_region);
  fd.set("dest_school", values.dest_school);
  fd.set("items", JSON.stringify(items.map((it) => ({ barcode: it.barcode }))));
  fd.set("fingerprint", fingerprint);
  if (turnstileToken) fd.set("turnstile_token", turnstileToken);
  items.forEach((it, i) => {
    if (it.front) fd.set(`photo_${i}_front`, it.front);
    if (it.back) fd.set(`photo_${i}_back`, it.back);
  });
  return fd;
}

/** 照片文件预检：类型必须是图片、大小 ≤5MB（后端会再拦，这里给即时反馈）。 */
export function checkPhotoFile(file: File): string | null {
  if (!file.type.startsWith("image/")) return "请选择图片文件（JPG / PNG 等）";
  if (file.size > MAX_PHOTO_BYTES) return "照片超过 5MB 上限，请压缩后重试";
  return null;
}

/** 是否还有「待 AI 审核」的条目（驱动历史区轻量轮询）。 */
export function needsReviewPoll(regs: PostcardRegistrationSummary[]): boolean {
  return (regs || []).some((r) =>
    r.items.some((it) => it.review_state === "pending"),
  );
}

/**
 * 终态失败（ai_failed / manual_failed）提交的轮询凭证：关页 sendBeacon 清照片用。
 * 未发放登记码的提交没有明文码，清理只能走 token（2026-11-08 起）。
 */
export function failedReviewTokens(regs: PostcardRegistrationSummary[]): string[] {
  return (regs || [])
    .filter((r) =>
      r.status !== "cancelled" &&
      r.items.some(
        (it) => it.review_state === "ai_failed" || it.review_state === "manual_failed",
      ),
    )
    .map((r) => r.access_token || "")
    .filter((t) => t.length > 0);
}

/** 终态失败（ai_failed / manual_failed）的登记单号：关页 sendBeacon 清照片用。 */
export function failedReviewRegCodes(regs: PostcardRegistrationSummary[]): string[] {
  return (regs || [])
    .filter((r) =>
      r.status !== "cancelled" &&
      r.items.some(
        (it) => it.review_state === "ai_failed" || it.review_state === "manual_failed",
      ),
    )
    .map((r) => r.reg_code);
}

/** 登记单里是否有「AI 不匹配」条目（决定「申请人工复核」按钮）。 */
export function hasAiFailedItem(reg: PostcardRegistrationSummary): boolean {
  return reg.items.some((it) => it.review_state === "ai_failed");
}

/**
 * 审核结论（用户侧发放登记码的唯一依据，2026-11-08 用户指定）：
 * - **AI 通过**（全部 ai_passed / manual_passed）→ 发码；
 * - **转人工**（存在 manual_pending）→ 立即发码（不等人工结果）；
 * - **失败**（ai_failed / manual_failed）→ 不发码，告知哪项不匹配，
 *   申请人工复核转 manual_pending 后再发码；
 * - 其余（仍有 pending）→ 继续等。
 */
export type ReviewOutcome =
  | { kind: "granted"; via: "ai" | "manual" }
  | { kind: "rejected"; mismatched: string[]; comment: string }
  | { kind: "pending" };

export function reviewOutcomeOf(reg: PostcardRegistrationSummary): ReviewOutcome {
  const items = reg.items || [];
  if (items.length === 0) return { kind: "pending" };
  const failed = items.filter(
    (it) => it.review_state === "ai_failed" || it.review_state === "manual_failed",
  );
  if (failed.length > 0) {
    const mismatched = [...new Set(failed.flatMap((it) => it.mismatched || []))];
    const comment = failed.find((it) => it.comment)?.comment || "";
    return { kind: "rejected", mismatched, comment };
  }
  if (items.some((it) => it.review_state === "manual_pending")) {
    return { kind: "granted", via: "manual" };
  }
  if (items.every((it) => it.review_state === "ai_passed" || it.review_state === "manual_passed")) {
    return { kind: "granted", via: "ai" };
  }
  return { kind: "pending" };
}
