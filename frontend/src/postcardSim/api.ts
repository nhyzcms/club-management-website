/**
 * 模拟环境的管理端 API 实现：形状与 `api/postcardAdmin.ts` 的 `postcardAdminApi`
 * 完全一致，因此**管理端 6 个 tab 的源码一行都不用改**（切换在 postcardAdmin.ts
 * 的 Proxy 里做）。
 *
 * 分工（2026-11-08 用户确认）：
 * - 活动配置 / 条码 / 登记记录 / 统计 / 建议与审计 → 全部读写内存 state，绝不打后端；
 * - AI 相关 → **真实调用后端**（用户要求能验证真实链路）：加载时带入正式环境里
 *   已保存的非敏感参数作为初值，测试连接时可带临时参数（后端不落库），
 *   「让 AI 读样例」把内存里的样例图临时上传给后端解读。
 * - 导出文件在浏览器里现造（见 files.ts），文件名由 downloadWithCredentials
 *   自动追加「-仅限模拟环境使用」。
 */
import {
  POSTCARD_GRADES,
  realPostcardAdminApi,
  type AdminConfig,
  type AdminConfigInput,
  type AIConfig,
  type AISample,
  type AuditRow,
  type BarcodeSummary,
  type Paged,
  type PostcardAdminApi,
  type ReceiptPayload,
  type RecordQuery,
  type RecordRow,
  type ReviewRow,
  type SchoolsImportResult,
  type StatsPayload,
  type SuggestionRow,
} from "../api/postcardAdmin";
import { createRequest } from "../api/shared";
import {
  SIM_PAGE_SIZE,
  SimError,
  auditPage,
  barcodeSummary,
  configPayload,
  deleteRegistration as deleteReg,
  emptySimState,
  generateBarcodes,
  newSeason,
  publish,
  archiveSeason,
  photoDataUrl,
  REVIEW_LABELS,
  syncRegistrationStatus,
  recordsPage,
  saveConfig,
  statsOf,
  suggestionsPage,
  updateRegistration as updateReg,
  type SimState,
} from "./state";
import {
  PDF_MIME,
  XLSX_MIME,
  buildPdf,
  buildXlsx,
  bytesToDataUrl,
} from "./files";

const request = createRequest("/events/postcard");

const GRADE_LABELS: Record<string, string> = Object.fromEntries(
  POSTCARD_GRADES.map((g) => [g.value, g.label]),
);

const REG_STATUS_LABELS: Record<string, string> = {
  registered: "已登记",
  reported: "已报寄",
  cancelled: "已取消",
};

function readFileDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new SimError("读取本地图片失败。"));
    reader.readAsDataURL(file);
  });
}

/** 条码 PDF：模拟里只列前 100 个 + 说明（真实 PDF 由服务端 reportlab 出）。 */
function barcodePdfUrl(state: SimState): string {
  if (state.barcodes.length === 0) throw new SimError("还没有条码，先生成再导出。");
  const lines: string[] = [
    "POSTCARD BARCODES - SIMULATION ONLY",
    "This file is generated in your browser for the simulation environment.",
    `total: ${state.barcodes.length}`,
    "",
  ];
  const sample = state.barcodes.slice(0, 100).map((b) => b.code);
  for (let i = 0; i < sample.length; i += 10) lines.push(sample.slice(i, i + 10).join("   "));
  if (state.barcodes.length > sample.length) {
    lines.push("", `... ${state.barcodes.length - sample.length} more codes omitted (simulation)`);
  }
  const pages: string[][] = [];
  for (let i = 0; i < lines.length; i += 60) pages.push(lines.slice(i, i + 60));
  return bytesToDataUrl(buildPdf(pages), PDF_MIME);
}

/** 记录导出：把当前筛选下的全部行摊成表格（与屏幕口径一致）。 */
function buildExportUrl(state: SimState, params: RecordQuery, fmt: "xlsx" | "pdf"): string {
  const all: RecordRow[] = [];
  for (let page = 1; ; page += 1) {
    const chunk = recordsPage(state, { ...params, page });
    all.push(...chunk.results);
    if (!chunk.next) break;
    if (page > 500) break;
  }
  const header = ["条码", "登记码", "寄出人", "年级", "班级", "寄达区", "寄达校", "状态", "登记时间"];
  const rows = all.map((r) => [
    r.barcode,
    r.registration.reg_code,
    r.registration.sender_name,
    r.registration.grade_label,
    `${r.registration.class_no}`,
    r.registration.dest_region,
    r.registration.dest_school,
    r.registration.status_label,
    r.registration.created_at.replace("T", " ").slice(0, 19),
  ]);
  if (fmt === "xlsx") {
    return bytesToDataUrl(buildXlsx([header, ...rows]), XLSX_MIME);
  }
  // PDF 走 ASCII（Courier 无中文字形）：列序与屏幕一致，表头用英文。
  const enHeader = "barcode  reg_code  sender  grade  class  region  school  status  time";
  const lines = [
    "POSTCARD REGISTRATIONS - SIMULATION ONLY",
    `rows: ${rows.length}`,
    "",
    enHeader,
    ...rows.map((r) => r.join("  ")),
  ];
  const pages: string[][] = [];
  for (let i = 0; i < lines.length; i += 60) pages.push(lines.slice(i, i + 60));
  return bytesToDataUrl(buildPdf(pages), PDF_MIME);
}

function receiptOf(state: SimState, barcode: string): ReceiptPayload {
  for (const reg of state.registrations) {
    const item = reg.items.find((i) => i.barcode === barcode);
    if (!item) continue;
    return {
      barcode,
      item_status: item.status,
      item_status_label: REG_STATUS_LABELS[item.status],
      already_reported: item.status === "reported",
      registration: {
        reg_code: reg.reg_code,
        sender_name: reg.sender_name,
        grade_label: GRADE_LABELS[reg.grade] || reg.grade,
        class_no: reg.class_no,
        dest_region: reg.dest_region,
        dest_school: reg.dest_school,
        status: reg.status,
        status_label: REG_STATUS_LABELS[reg.status],
        created_at: reg.created_at,
        items: reg.items.map((i) => ({
          id: i.id,
          barcode: i.barcode,
          status: i.status,
          status_label: REG_STATUS_LABELS[i.status],
        })),
      },
    };
  }
  throw new SimError("明信片未登记，请先登记！", 404);
}

/** 已播种过 AI 配置的 state（按对象身份记，避免重复请求）。 */
const aiSeededStates = new WeakSet<SimState>();

/**
 * 把正式环境里已保存的 AI 参数带进模拟（只读、不含 api_key）。
 *
 * 管理端 tab 与用户端登记（要真调 `admin/ai/preview/`）都依赖它，所以抽成
 * 独立函数；session 进入模拟时就预热一次。
 */
export async function seedSimAIConfig(state: SimState): Promise<void> {
  if (aiSeededStates.has(state)) return;
  aiSeededStates.add(state);
  try {
    const real = await realPostcardAdminApi.aiConfig();
    state.ai.base_url = real.base_url || "";
    state.ai.model = real.model || "";
    state.ai.enabled = Boolean(real.enabled);
    state.ai.timeout_seconds = real.timeout_seconds ?? 20;
    state.ai.extra_headers = { ...(real.extra_headers || {}) };
    state.ai.ip_blacklist = [...(real.ip_blacklist || [])];
    state.ai.prompt_prefix = real.prompt_prefix || "";
    state.ai.api_key_set = Boolean(real.api_key_set);
  } catch {
    // 正式环境还没配过 / 网络异常：保持空配置，模拟照常可用。
  }
}

/** 造一个模拟管理端 API（共用传进来的内存 state；退出即整体丢弃）。 */
export function createSimPostcardAdminApi(state: SimState = emptySimState()): PostcardAdminApi {
  /** 模拟环境的 AI 临时参数：只随本次请求发给后端，不落库、不写审计。 */
  function aiOverrides(): Record<string, unknown> {
    const overrides: Record<string, unknown> = {};
    if (state.ai.base_url) overrides.base_url = state.ai.base_url;
    if (state.ai.model) overrides.model = state.ai.model;
    if (state.ai.timeout_seconds) overrides.timeout_seconds = state.ai.timeout_seconds;
    if (Object.keys(state.ai.extra_headers).length) overrides.extra_headers = state.ai.extra_headers;
    if (state.ai.ip_blacklist.length) overrides.ip_blacklist = state.ai.ip_blacklist;
    if (state.ai.prompt_prefix) overrides.prompt_prefix = state.ai.prompt_prefix;
    if (state.ai.api_key) overrides.api_key = state.ai.api_key;
    overrides.dry_run = true;
    return overrides;
  }

  async function aiConfig(): Promise<AIConfig> {
    await seedSimAIConfig(state);
    return {
      configured: Boolean(state.ai.base_url || state.ai.model),
      enabled: state.ai.enabled,
      ready: Boolean(state.ai.enabled && state.ai.base_url && state.ai.model && state.ai.api_key_set),
      base_url: state.ai.base_url,
      model: state.ai.model,
      extra_headers: { ...state.ai.extra_headers },
      timeout_seconds: state.ai.timeout_seconds,
      ip_blacklist: [...state.ai.ip_blacklist],
      prompt_prefix: state.ai.prompt_prefix,
      api_key_set: state.ai.api_key_set,
    };
  }

  const api: PostcardAdminApi = {
    // —— 活动配置 ——
    getConfig: async () => configPayload(state),
    saveConfig: async (input: AdminConfigInput, pdf?: File | null, clearPdf?: boolean) =>
      saveConfig(state, input, { pdf, clearPdf }),
    publish: async () => {
      publish(state);
      return { status: "published" };
    },
    archiveSeason: async () => {
      archiveSeason(state);
      return { status: "archived" };
    },
    newSeason: () => {
      const r = newSeason(state);
      return Promise.resolve({ event_id: r.event_id, previous_event: r.previous_event, status: "draft" });
    },

    // —— 条码 ——
    barcodes: async () => barcodeSummary(state) as BarcodeSummary,
    generateBarcodes: async (count: number, replace = false) => generateBarcodes(state, count, replace),
    barcodePdfUrl: () => barcodePdfUrl(state),

    // —— AI（真实调用后端）——
    aiConfig,
    saveAIConfig: async (patch) => {
      if (patch.enabled !== undefined) state.ai.enabled = patch.enabled;
      if (patch.base_url !== undefined) state.ai.base_url = patch.base_url;
      if (patch.model !== undefined) state.ai.model = patch.model;
      if (patch.timeout_seconds !== undefined) state.ai.timeout_seconds = patch.timeout_seconds;
      if (patch.extra_headers !== undefined) state.ai.extra_headers = { ...patch.extra_headers };
      if (patch.ip_blacklist !== undefined) state.ai.ip_blacklist = [...patch.ip_blacklist];
      if (patch.prompt_prefix !== undefined) state.ai.prompt_prefix = patch.prompt_prefix;
      if (patch.api_key) {
        state.ai.api_key = patch.api_key;
        state.ai.api_key_set = true;
      }
      return aiConfig();
    },
    testAIConfig: async () => {
      // 带临时参数：后端只在这次请求里用，不落库（不在模拟里写正式配置）。
      const overrides = aiOverrides();
      return request<{ ok: boolean; error?: string; latency_ms?: number; model?: string; reply?: string }>(
        "/admin/ai/test/",
        { method: "POST", body: JSON.stringify(overrides) },
      );
    },
    aiModels: async () => {
      // 与测试连接同口径：用模拟里填的参数真拉一次服务商 /models，不落库。
      return request<{ ok: boolean; models?: string[]; error?: string }>(
        "/admin/ai/models/",
        { method: "POST", body: JSON.stringify(aiOverrides()) },
      );
    },
    aiSamples: async () => ({
      results: state.samples.map<AISample>((s) => ({
        id: s.id,
        caption: s.caption,
        has_image: Boolean(s.data_url),
        created_at: new Date().toISOString(),
      })),
      sample_ready: state.samples.length > 0,
    }),
    uploadAISample: async (image: File, caption: string) => {
      const dataUrl = await readFileDataUrl(image);
      const id = state.seq;
      state.seq += 1;
      state.samples.push({ id, caption, data_url: dataUrl });
      return { id, caption, sample_ready: true };
    },
    deleteAISample: async (id: number) => {
      const before = state.samples.length;
      state.samples = state.samples.filter((s) => s.id !== id);
      return { deleted: before - state.samples.length, sample_ready: state.samples.length > 0 };
    },
    aiSampleImageUrl: (id: number) => state.samples.find((s) => s.id === id)?.data_url || "",
    explainAISample: async (id: number) => {
      const sample = state.samples.find((s) => s.id === id);
      if (!sample) throw new SimError("样例不存在。", 404);
      const blob = await (await fetch(sample.data_url)).blob();
      const fd = new FormData();
      fd.set("image", new File([blob], "sample.jpg", { type: blob.type || "image/jpeg" }));
      fd.set("caption", sample.caption || "");
      return request<{ text: string }>("/admin/ai/explain/", { method: "POST", body: fd });
    },

    // —— 导入海报（AI 识别本身不落库：真跑正式环境的 AI，结果只进内存表单）——
    importSchools: (image: File) => {
      const fd = new FormData();
      fd.set("image", image);
      fd.set("dry_run", "1");
      return request<SchoolsImportResult>("/admin/schools/import/", { method: "POST", body: fd });
    },

    // —— 复核台（PR2 接页面；这里先把数据结构打通）——
    reviewQueue: async (page = 1, reviewState = "") => {
      const rows: ReviewRow[] = [];
      for (const reg of state.registrations) {
        for (const item of reg.items) {
          if (item.review_state !== "manual_pending" && item.review_state !== "ai_failed") continue;
          if (reviewState && item.review_state !== reviewState) continue;
          rows.push({
            id: item.id,
            item_id: item.id,
            barcode: item.barcode,
            review_state: item.review_state,
            photo_ids: item.photos.map((p) => p.id),
            ai_verdict: item.ai_verdict,
            registration: {
              registration_id: reg.id,
              reg_code: reg.reg_code,
              sender_name: reg.sender_name,
              grade_label: GRADE_LABELS[reg.grade] || reg.grade,
              class_no: reg.class_no,
              dest_region: reg.dest_region,
              dest_school: reg.dest_school,
              created_at: reg.created_at,
            },
          });
        }
      }
      const start = (Math.max(1, page) - 1) * SIM_PAGE_SIZE;
      return {
        count: rows.length,
        next: start + SIM_PAGE_SIZE < rows.length ? String(page + 1) : null,
        previous: page > 1 ? String(page - 1) : null,
        results: rows.slice(start, start + SIM_PAGE_SIZE),
      } as Paged<ReviewRow>;
    },
    reviewDecision: async (itemId: number, decision: "pass" | "fail", note: string) => {
      for (const reg of state.registrations) {
        const item = reg.items.find((i) => i.id === itemId);
        if (!item) continue;
        item.review_state = decision === "pass" ? "manual_passed" : "manual_failed";
        if (decision === "pass") {
          // 通过即删照片（与正式环境的生命周期一致）。
          item.photos = [];
        }
        // 人工判定覆盖 AI 判定，但保留原判定供追溯（后端 AdminReviewDecisionView 同口径）。
        item.ai_verdict = {
          manual: { decision, note },
          ai_verdict: item.ai_verdict,
        };
        // 注意：这里**不改**登记单 / 明信片状态。后端只改照片的复核态，
        // 「人工不通过」不等于「取消登记」——之前模拟里把它一并取消是错的。
        return {
          item_id: itemId,
          review_state: item.review_state,
          review_label: REVIEW_LABELS[item.review_state],
        };
      }
      throw new SimError("复核条目不存在。", 404);
    },
    reviewPhotoUrl: (photoId: number) => photoDataUrl(state, photoId),
    // —— 登记记录 ——
    records: async (params: RecordQuery) => recordsPage(state, params),
    updateRegistration: async (registrationId: number, patch) => updateReg(state, registrationId, patch),
    deleteRegistration: async (registrationId: number) => {
      deleteReg(state, registrationId);
      return null;
    },
    exportUrl: (params, fmt) => buildExportUrl(state, params, fmt),

    // —— 统计 ——
    stats: async () => statsOf(state),

    // —— 建议 / 审计 ——
    suggestions: async (page = 1) => suggestionsPage(state, page) as Paged<SuggestionRow>,
    audit: async (page = 1) => auditPage(state, page) as Paged<AuditRow>,

    // —— 签收 ——
    lookup: async (barcode: string) => receiptOf(state, barcode),
    confirm: async (barcode: string) => {
      const reg = state.registrations.find((r) => r.items.some((i) => i.barcode === barcode));
      const item = reg?.items.find((i) => i.barcode === barcode);
      if (!reg || !item) throw new SimError("明信片未登记，请先登记！", 404);
      if (item.status === "cancelled") throw new SimError("该明信片所属登记已取消，无法签收。");
      if (item.status === "reported") {
        const already = receiptOf(state, barcode);
        return { ...already, already_reported: true };
      }
      item.status = "reported";
      // 登记单状态由条目联动（全部未取消的条目都报寄才算「已报寄」）。
      syncRegistrationStatus(reg);
      return receiptOf(state, barcode);
    },
    unreport: async (barcode: string) => {
      const reg = state.registrations.find((r) => r.items.some((i) => i.barcode === barcode));
      const item = reg?.items.find((i) => i.barcode === barcode);
      if (!reg || !item) throw new SimError("明信片未登记，请先登记！", 404);
      if (item.status !== "reported") throw new SimError("该条码不是已报寄状态。");
      item.status = "registered";
      syncRegistrationStatus(reg);
      return receiptOf(state, barcode);
    },
  };

  return api;
}
