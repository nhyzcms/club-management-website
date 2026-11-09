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
  requestManualReview,
  submitRegistration,
  updateOwnRegistration,
  type SimState,
  type SubmitItemInput,
} from "./state";

function readFileDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new SimError("读取本地照片失败。"));
    reader.readAsDataURL(file);
  });
}

/** 逐张读取 `photo_<i>_front/back` 并转成 data URL（模拟环境不落任何存储）。 */
async function readPhotos(form: FormData, index: number): Promise<SubmitItemInput["photos"]> {
  const photos: SubmitItemInput["photos"] = [];
  for (const side of ["front", "back"] as const) {
    const file = form.get(`photo_${index}_${side}`);
    if (file instanceof Blob && file.size > 0) {
      photos.push({ side, data_url: await readFileDataUrl(file) });
    }
  }
  return photos;
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

export function createSimPostcardUserApi(state: SimState): PostcardApi {
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
      const items: SubmitItemInput[] = [];
      for (let i = 0; i < parsed.length; i += 1) {
        items.push({ barcode: String(parsed[i].barcode || ""), photos: await readPhotos(form, i) });
      }
      return submitRegistration(state, {
        sender_name: String(form.get("sender_name") || ""),
        grade: String(form.get("grade") || ""),
        class_no: Number(form.get("class_no") || 0),
        dest_region: String(form.get("dest_region") || ""),
        dest_school: String(form.get("dest_school") || ""),
        fingerprint: String(form.get("fingerprint") || ""),
        items,
      });
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

    update: async (regCode, patch) => updateOwnRegistration(state, regCode, patch),

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
