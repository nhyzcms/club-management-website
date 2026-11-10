/**
 * 模拟环境的用户端 API（`#/postcard?sim=1`）：形状与 `api/postcard.ts` 的
 * `postcardApi` 完全一致，因此登记表单、历史区、查询框、建议箱一行都不用改。
 *
 * 与管理端 API 共用同一份内存 state（同一个 `createSimSession()` 造出来），
 * 所以「在模拟里登记 → 管理端看到记录 → 审核台复核 → 签收页签收」是真正联动
 * 的一条链，只是全部发生在内存里，退出即清空。
 */
import type {
  PostcardApi,
  PostcardRegistrationSummary,
  RegisterResult,
} from "../api/postcard";
import { POSTCARD_GRADES } from "../api/postcardAdmin";
import { createRequest } from "../api/shared";
import { PDF_MIME, buildPdf, bytesToDataUrl } from "./files";
import {
  SimError,
  addSuggestion,
  cancelOwnRegistration,
  findRegistrationByCode,
  findRegistrationByToken,
  lookupRegistrations,
  myRegistrations,
  photoDataUrl,
  portalOf,
  registrationSummary,
  aiReady,
  requestManualReview,
  submitRegistration,
  updateOwnRegistration,
  type SimState,
  type SubmitItemInput,
  type SimVerdict,
} from "./state";

const request = createRequest("/events/postcard");

const GRADE_LABELS: Record<string, string> = Object.fromEntries(
  POSTCARD_GRADES.map((g) => [g.value, g.label]),
);

/** 与后端 photos.MAX_EDGE / JPEG_QUALITY 同参数。 */
const MAX_EDGE = 1280;
const JPEG_QUALITY = 0.8;

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image decode failed"));
    img.src = src;
  });
}

/**
 * 模拟环境的照片压缩：最长边 1280、JPEG 0.8（照抄后端照片管线）。
 *
 * 不做这一步的话，5 张 × 2 面的原图 data URL 能吃掉几十 MB 内存，手机上直接卡死；
 * 正式环境本来就会重编码，模拟里也保持一致，教学时看到的「通过即删照片」才有意义。
 * SVG / 跨源图会污染 canvas（toDataURL 抛错）→ 退回原始 data URL，不影响流程。
 */
async function photoToDataUrl(file: Blob): Promise<string> {
  const raw = await readFileDataUrl(file);
  try {
    const img = await loadImage(raw);
    const edge = Math.max(img.width, img.height);
    if (!edge) return raw;
    const scale = Math.min(1, MAX_EDGE / edge);
    if (scale === 1 && raw.length < 400_000) return raw;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.width * scale));
    canvas.height = Math.max(1, Math.round(img.height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return raw;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  } catch {
    return raw;
  }
}

function readFileDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new SimError("读取本地照片失败。"));
    reader.readAsDataURL(file);
  });
}

/** 取第 i 张明信片的两面原始文件（预览要原图上传，内存里再存压缩后的 data URL）。 */
function readPhotoFiles(form: FormData, index: number): { side: "front" | "back"; file: Blob }[] {
  const files: { side: "front" | "back"; file: Blob }[] = [];
  for (const side of ["front", "back"] as const) {
    const file = form.get(`photo_${index}_${side}`);
    if (file instanceof Blob && file.size > 0) files.push({ side, file });
  }
  return files;
}

function announcementPdfUrl(state: SimState): string {
  const body = state.config?.announcement_body || "";
  const lines = [
    "POSTCARD ANNOUNCEMENT - SIMULATION ONLY",
    "",
    ...body
      .replace(/<[^>]+>/g, " ")
      .split(/\n+/)
      .flatMap((line) => (line.trim() ? [line.trim()] : [])),
  ];
  const pages: string[][] = [];
  for (let i = 0; i < lines.length; i += 60) pages.push(lines.slice(i, i + 60));
  return bytesToDataUrl(buildPdf(pages.length ? pages : [[""]]), PDF_MIME);
}

export interface SimUserApiDeps {
  /** 真调 `admin/ai/preview/` 拿判定；返回 null 表示 AI 不可用（转人工）。测试可注入。 */
  previewAIReview?: (form: FormData) => Promise<SimVerdict | null>;
}

async function defaultPreviewAIReview(form: FormData): Promise<SimVerdict | null> {
  const res = await request<{ ok: boolean; verdict?: SimVerdict; reason?: string }>(
    "/admin/ai/preview/",
    { method: "POST", body: form },
  );
  return res.ok && res.verdict ? res.verdict : null;
}

export function createSimPostcardUserApi(
  state: SimState,
  deps: SimUserApiDeps = {},
): PostcardApi {
  const previewAIReview = deps.previewAIReview ?? defaultPreviewAIReview;
  const api: PostcardApi = {
    portal: async () => portalOf(state),

    register: async (form: FormData): Promise<RegisterResult> => {
      const itemsRaw = String(form.get("items") || "[]");
      let parsed: { barcode: string }[] = [];
      try {
        parsed = JSON.parse(itemsRaw);
      } catch {
        throw new SimError("提交的数据格式有误，请重试。");
      }
      const senderName = String(form.get("sender_name") || "");
      const grade = String(form.get("grade") || "");
      const classNo = Number(form.get("class_no") || 0);
      const destRegion = String(form.get("dest_region") || "");
      const destSchool = String(form.get("dest_school") || "");

      const items: SubmitItemInput[] = [];
      const verdicts: (SimVerdict | null)[] = [];
      for (let i = 0; i < parsed.length; i += 1) {
        const barcode = String(parsed[i].barcode || "");
        const files = readPhotoFiles(form, i);
        const photos: SubmitItemInput["photos"] = [];
        for (const f of files) {
          photos.push({ side: f.side, data_url: await photoToDataUrl(f.file) });
        }
        items.push({ barcode, photos });

        // 与正式流程一致：AI 配齐就真跑一次判定（不落库）；不配就直接转人工。
        if (!aiReady(state)) {
          verdicts.push(null);
          continue;
        }
        const fd = new FormData();
        fd.set("sender_name", senderName);
        fd.set("grade_label", GRADE_LABELS[grade] || grade);
        fd.set("class_no", String(classNo));
        fd.set("dest_region", destRegion);
        fd.set("dest_school", destSchool);
        fd.set("barcode", barcode);
        for (const f of files) fd.set(`photo_${f.side}`, f.file);
        try {
          verdicts.push(await previewAIReview(fd));
        } catch {
          // 调用失败 = 与正式环境的降级一致：转人工复核（不阻断登记）。
          verdicts.push(null);
        }
      }
      return submitRegistration(state, {
        sender_name: String(form.get("sender_name") || ""),
        grade: String(form.get("grade") || ""),
        class_no: Number(form.get("class_no") || 0),
        dest_region: String(form.get("dest_region") || ""),
        dest_school: String(form.get("dest_school") || ""),
        fingerprint: String(form.get("fingerprint") || ""),
        items,
      }, new Date(), verdicts);
    },

    my: async (fingerprint: string) => ({ results: myRegistrations(state, fingerprint) }),

    detail: async (regCode: string, _fingerprint: string, submissionId?: number) => {
      const reg = findRegistrationByCode(state, regCode);
      if (!reg) throw new SimError("登记单不存在或登记码有误。", 404);
      const summary = registrationSummary(reg);
      if (!submissionId) return summary;
      // 同一登记码多份提交时，`id` 定位到具体那一份。
      const one = reg.items.find((it) => it.id === submissionId);
      if (!one) throw new SimError("这条提交不存在。", 404);
      return { ...summary, items: summary.items.filter((it) => it.id === one.id) };
    },

    statusByToken: async (token: string): Promise<PostcardRegistrationSummary> => {
      const reg = findRegistrationByToken(state, token);
      if (!reg) throw new SimError("凭证已过期，请刷新页面。", 404);
      return registrationSummary(reg);
    },

    lookup: async (q: string) => lookupRegistrations(state, q),

    update: async (regCode, patch, _fingerprint, submissionId) =>
      updateOwnRegistration(state, regCode, patch, submissionId),

    cancel: async (regCode, _fingerprint, scope = "one", submissionId) =>
      cancelOwnRegistration(state, regCode, scope, submissionId),

    requestReview: async (regCode: string) => requestManualReview(state, { regCode }),

    requestReviewByToken: async (token: string) => requestManualReview(state, { token }),

    suggest: async (content: string, contact: string) => {
      addSuggestion(state, content, contact);
      return { message: "建议已收到，谢谢！" };
    },

    // 照片就是内存里的 data URL：<img src> 直接可用。
    photoUrl: (photoId: number) => photoDataUrl(state, photoId),

    announcementPdfUrl: () => announcementPdfUrl(state),
  };
  return api;
}
