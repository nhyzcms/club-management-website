/**
 * 明信片互寄 · 管理端 API（后端 events/modules/postcard/urls.py 的 `admin/` 段）。
 *
 * 权限：`events.manage_postcard`（配置 / 条码 / AI / 记录 / 统计 / 建议 / 审计）
 * 与 `events.review_postcard`（复核台 / 签收）。前端不做权限判定——403 由各面板
 * 显示「需要管理员权限」，真源始终在服务端（命名权限）。
 *
 * 配置写入口是 multipart：公告 PDF 只能走文件上传，而 HTML 表单的列表字段
 * 只能是字符串，因此 `destination_schools` 以 JSON 串提交（后端 JSONListField 解码）。
 */
import { createRequest } from "./shared";

const request = createRequest("/events/postcard");

export type PostcardPhase = "not_started" | "registering" | "shipped" | "distributing" | "ended";

export interface AdminSchool {
  region: string;
  name: string;
  /** 区内编号（「浦东新区1」→ 1）；区内按它排序。 */
  no?: number | null;
}

/** 「导入海报」AI 识别结果：只回解析结果，落库仍走 saveConfig。 */
export interface ImportedSchool {
  region: string;
  name: string;
  no: number | null;
}

export interface SchoolsImportResult {
  schools: ImportedSchool[];
  /** 无法归属区 / 名称的条目（面向管理员的原因文案，最多 20 条）。 */
  skipped: string[];
  /** 识别出学校但没识别出编号的条数（需管理员手补）。 */
  missing_no: number;
}

export interface AdminEventShell {
  id: number;
  title: string;
  summary: string;
  status: string;
  start_at: string;
  end_at: string | null;
}

export interface AdminConfig {
  configured: boolean;
  phase?: PostcardPhase;
  phase_label?: string;
  event?: AdminEventShell | null;
  announcement_body?: string;
  has_announcement_pdf?: boolean;
  allowed_grades?: string[];
  destination_schools?: AdminSchool[];
  ship_at?: string | null;
  distribute_at?: string | null;
  barcode_count?: number;
  registration_count?: number;
}

export interface AdminConfigInput {
  title: string;
  summary: string;
  body: string;
  start_at: string;
  end_at: string;
  ship_at: string | null;
  distribute_at: string | null;
  allowed_grades: string[];
  destination_schools: AdminSchool[];
}

export interface BarcodeSummary {
  configured: boolean;
  total?: number;
  /** 已被登记占用（已发出去）的条码数——覆盖生成时会被保护。 */
  bound?: number;
  min?: number;
  max?: number;
  step?: number;
  default?: number;
}

export interface AIConfig {
  configured: boolean;
  enabled?: boolean;
  ready?: boolean;
  base_url?: string;
  model?: string;
  extra_headers?: Record<string, string>;
  timeout_seconds?: number;
  ip_blacklist?: string[];
  api_key_set?: boolean;
}

export interface AIModelsResult {
  ok: boolean;
  models?: string[];
  error?: string;
}

/** 临时覆盖的 AI 连接参数（模拟环境 / 未保存草稿试连用，后端不落库）。 */
export interface AIProbeInput {
  base_url?: string;
  api_key?: string;
  model?: string;
  extra_headers?: Record<string, string>;
  timeout_seconds?: number;
  dry_run?: boolean;
}

export interface AISample {
  id: number;
  caption: string;
  has_image: boolean;
  created_at?: string;
}

export interface Paged<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface RecordRow {
  item_id: number;
  barcode: string;
  item_status: string;
  item_status_label: string;
  registration: {
    /** 单份提交 id（同一登记码可能对应多份提交）。 */
    registration_id: number;
    reg_code: string;
    sender_name: string;
    grade: string;
    grade_label: string;
    class_no: number;
    dest_region: string;
    dest_school: string;
    status: string;
    status_label: string;
    created_at: string;
  };
}

export interface ReviewRow {
  /** 审核台通用首键（firstOf 依赖 id）。 */
  id: number;
  item_id: number;
  barcode: string;
  review_state: string | null;
  photo_ids: number[];
  ai_verdict: Record<string, any> | null;
  registration: {
    registration_id: number;
    reg_code: string;
    sender_name: string;
    grade_label: string;
    class_no: number;
    dest_region: string;
    dest_school: string;
    created_at: string;
  };
}

export interface StatsPayload {
  registrations: { total: number; registered: number; reported: number; cancelled: number };
  items: { total: number; registered: number; reported: number; cancelled: number };
  destination_schools: number;
  by_school: { school: string; total: number; reported: number }[];
  by_grade: { grade: string; total: number }[];
  by_day: { day: string | null; total: number }[];
}

export interface SuggestionRow {
  id: number;
  content: string;
  contact: string;
  created_at: string;
}

export interface AuditRow {
  id: number;
  action: string;
  target: string;
  detail: Record<string, any> | null;
  user: string | null;
  ip: string | null;
  created_at: string;
}

/** 签收查询 / 确认的公共载荷。 */
export interface ReceiptPayload {
  barcode: string;
  item_status?: string;
  item_status_label?: string;
  already_reported?: boolean;
  registration: {
    reg_code: string;
    sender_name: string;
    grade_label: string;
    class_no: number;
    dest_region: string;
    dest_school: string;
    status: string;
    status_label: string;
    created_at: string;
    items?: { id: number; barcode: string; status: string; status_label: string }[];
  };
}

/** 记录筛选参数（记录列表与导出共用）。 */
export interface RecordQuery {
  q?: string;
  status?: string;
  item_status?: string;
  grade?: string;
  class_no?: string;
  school?: string;
  region?: string;
  page?: number;
}

function query(params: RecordQuery & { fmt?: string }): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    sp.set(k, String(v));
  }
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

/** 模拟环境导出的文件名标记（`明信片登记-2026-11-08-仅限模拟环境使用.xlsx`）。 */
export const SIM_FILE_SUFFIX = "-仅限模拟环境使用";

export function withSimFileSuffix(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0
    ? `${filename.slice(0, dot)}${SIM_FILE_SUFFIX}${filename.slice(dot)}`
    : `${filename}${SIM_FILE_SUFFIX}`;
}

/**
 * 带会话下载（条码 PDF / 记录导出）。fetch → blob → <a download>，
 * 这样 403 / 400 能拿到后端 detail 文案，而不是开一个全是 JSON 的新标签页。
 */
export async function downloadWithCredentials(url: string, filename: string): Promise<void> {
  // 模拟环境的文件是浏览器现造的 data URL：不带 cookie，也不加鉴权头。
  const res = url.startsWith("data:") ? await fetch(url) : await fetch(url, { credentials: "include" });
  if (!res.ok) {
    let detail = `下载失败（${res.status}）`;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      /* 非 JSON 响应：沿用状态码文案 */
    }
    throw new Error(detail);
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  // 模拟环境导出的文件一律带标记，避免和正式导出混在下载目录里（用户要求）。
  a.download = isPostcardAdminSim() ? withSimFileSuffix(filename) : filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 立刻 revoke 会让部分浏览器取消下载，退一段时间再释放。
  window.setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

const realPostcardAdminApi = {
  // —— 活动配置 ——
  getConfig: () => request<AdminConfig>("/admin/config/"),

  saveConfig: (input: AdminConfigInput, pdf?: File | null, clearPdf?: boolean) => {
    const fd = new FormData();
    fd.set("title", input.title);
    fd.set("summary", input.summary);
    fd.set("body", input.body);
    fd.set("start_at", input.start_at);
    fd.set("end_at", input.end_at);
    if (input.ship_at) fd.set("ship_at", input.ship_at);
    if (input.distribute_at) fd.set("distribute_at", input.distribute_at);
    // 重复键 → DRF ListField 从 QueryDict.getlist 取值。
    for (const g of input.allowed_grades) fd.append("allowed_grades", g);
    // HTML 表单承载不了对象数组，序列化成 JSON 串（后端 JSONListField 解码）。
    fd.set("destination_schools", JSON.stringify(input.destination_schools));
    if (clearPdf) fd.set("clear_announcement_pdf", "1");
    if (pdf) fd.set("announcement_pdf", pdf);
    return request<AdminConfig>("/admin/config/", { method: "PUT", body: fd });
  },

  publish: () => request<{ status: string }>("/admin/publish/", { method: "POST" }),

  /** 归档当前活动（数据保留，不再参与「当前活动」推导）。 */
  archiveSeason: () => request<{ status: string }>("/admin/archive/", { method: "POST", body: "{}" }),

  /** 开启新一届：归档当前活动 + 新建草稿（复制年级与寄达校清单）。 */
  newSeason: () =>
    request<{ event_id: number; previous_event: number | null; status: string }>(
      "/admin/new-season/",
      { method: "POST", body: "{}" },
    ),

  // —— 条码 ——
  barcodes: () => request<BarcodeSummary>("/admin/barcodes/"),

  generateBarcodes: (count: number, replace = false) =>
    request<{ generated: number; total: number; replaced: boolean }>("/admin/barcodes/", {
      method: "POST",
      body: JSON.stringify({ count, replace }),
    }),

  barcodePdfUrl: () => "/events/postcard/admin/barcodes/pdf/",

  // —— AI 配置与样例 ——
  aiConfig: () => request<AIConfig>("/admin/ai/config/"),

  saveAIConfig: (patch: Partial<{
    enabled: boolean;
    base_url: string;
    api_key: string;
    model: string;
    extra_headers: Record<string, string>;
    timeout_seconds: number;
    ip_blacklist: string[];
  }>) =>
    request<AIConfig>("/admin/ai/config/", { method: "PUT", body: JSON.stringify(patch) }),

  /** 导入海报：AI 识别参与学校（区 + 区内编号 + 校名），只回结果不落库。 */
  importSchools: (image: File) => {
    const fd = new FormData();
    fd.set("image", image);
    return request<SchoolsImportResult>("/admin/schools/import/", { method: "POST", body: fd });
  },

  /** 测试连接：用已保存的配置发一次最小对话请求（不回显 api_key）。 */
  testAIConfig: () =>
    request<{ ok: boolean; error?: string; latency_ms?: number; model?: string; reply?: string }>(
      "/admin/ai/test/",
      { method: "POST", body: "{}" },
    ),

  /** 拉取服务商模型列表（{base_url}/models），供「模型选择」下拉；不内置清单。 */
  aiModels: (input: AIProbeInput = {}) =>
    request<AIModelsResult>("/admin/ai/models/", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  aiSamples: () => request<{ results: AISample[]; sample_ready: boolean }>("/admin/ai/samples/"),

  uploadAISample: (image: File, caption: string) => {
    const fd = new FormData();
    fd.set("image", image);
    fd.set("caption", caption);
    return request<{ id: number; caption: string; sample_ready: boolean }>("/admin/ai/samples/", {
      method: "POST",
      body: fd,
    });
  },

  deleteAISample: (id: number) =>
    request<{ deleted: number; sample_ready: boolean }>(`/admin/ai/samples/${id}/`, {
      method: "DELETE",
    }),

  aiSampleImageUrl: (id: number) => `/events/postcard/admin/ai/samples/${id}/image/`,

  /** 让 AI 复述它对这张样例的理解（管理员核对 AI 是否理解正确）。 */
  explainAISample: (id: number) =>
    request<{ text: string }>(`/admin/ai/samples/${id}/explain/`, {
      method: "POST",
      body: "{}",
    }),

  // —— 复核台 ——
  /** 复核队列：state = manual_pending / ai_failed / 空（全部）。 */
  reviewQueue: (page = 1, state = "") =>
    request<Paged<ReviewRow>>(
      `/admin/review/?page=${page}${state ? `&state=${encodeURIComponent(state)}` : ""}`,
    ),

  reviewDecision: (itemId: number, decision: "pass" | "fail", note: string) =>
    request<{ item_id: number; review_state: string; review_label: string }>(
      `/admin/review/${itemId}/`,
      { method: "POST", body: JSON.stringify({ decision, note }) },
    ),

  /** 复核台取图：manage / review 权限直达，无需登记码。 */
  reviewPhotoUrl: (photoId: number) => `/events/postcard/photo/${photoId}/`,

  // —— 登记记录 ——
  records: (params: RecordQuery) => request<Paged<RecordRow>>(`/admin/records/${query(params)}`),

  /** 按单份提交 id 修改（同一登记码多份提交时按码操作会被后端拒绝）。 */
  updateRegistration: (
    registrationId: number,
    patch: Partial<{
      sender_name: string;
      grade: string;
      class_no: number;
      dest_region: string;
      dest_school: string;
      status: string;
    }>,
  ) =>
    request<{ reg_code: string }>(`/admin/registrations/by-id/${registrationId}/`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteRegistration: (registrationId: number) =>
    request<null>(`/admin/registrations/by-id/${registrationId}/`, { method: "DELETE" }),

  exportUrl: (params: RecordQuery, fmt: "xlsx" | "pdf") =>
    `/events/postcard/admin/export/${query({ ...params, page: undefined, fmt })}`,

  // —— 统计 ——
  stats: () => request<StatsPayload>("/admin/stats/"),

  // —— 建议 / 审计 ——
  suggestions: (page = 1) => request<Paged<SuggestionRow>>(`/admin/suggestions/?page=${page}`),
  audit: (page = 1) => request<Paged<AuditRow>>(`/admin/audit/?page=${page}`),

  // —— 签收 ——
  lookup: (barcode: string) =>
    request<ReceiptPayload>(`/admin/lookup/?barcode=${encodeURIComponent(barcode)}`),
  confirm: (barcode: string) =>
    request<ReceiptPayload>("/admin/confirm/", {
      method: "POST",
      body: JSON.stringify({ barcode }),
    }),
  unreport: (barcode: string) =>
    request<ReceiptPayload>("/admin/unreport/", {
      method: "POST",
      body: JSON.stringify({ barcode }),
    }),
};

/** 管理端 API 的形状（真实现与模拟实现都满足它，Proxy 才能无缝切换）。 */
export type PostcardAdminApi = typeof realPostcardAdminApi;

/** 正式环境的真实现（模拟实现里需要调真实接口时用，绕过下面的 Proxy）。 */
export { realPostcardAdminApi };

/** 当前挂着的模拟实现（`?sim=1` 时由 postcardSim/session.ts 装上）。 */
let simApi: PostcardAdminApi | null = null;

export function installPostcardAdminSimApi(api: PostcardAdminApi | null): void {
  simApi = api;
}

/** 是否处于模拟环境（下载文件名加标识、徽标显示等处用）。 */
export function isPostcardAdminSim(): boolean {
  return simApi !== null;
}

/**
 * 管理端 API 入口。
 *
 * 正常情况直通真实现；模拟环境（`#/postcard/admin?sim=1`）下所有方法改路由到内存
 * 沙箱——管理端各 tab 的源码因此一行都不用改，界面与正式版天然一致。
 */
export const postcardAdminApi: PostcardAdminApi = new Proxy(realPostcardAdminApi, {
  get(target, prop, receiver) {
    if (simApi) {
      const impl = simApi as Record<PropertyKey, unknown>;
      const value = impl[prop];
      if (typeof value === "function") return (value as (...args: unknown[]) => unknown).bind(simApi);
    }
    return Reflect.get(target, prop, receiver);
  },
});

/** 16 区固定顺序（与后端 PostcardConfig.REGION_CHOICES 一致；2026-11-08 用户指定）。 */
export const POSTCARD_REGIONS = [
  "浦东新区", "宝山区", "崇明区", "奉贤区", "虹口区", "黄浦区", "嘉定区", "金山区",
  "静安区", "闵行区", "普陀区", "青浦区", "松江区", "徐汇区", "杨浦区", "长宁区",
];

/** 年级键值与文案（与后端 PostcardConfig.GRADE_CHOICES 一致）。 */
export const POSTCARD_GRADES: { value: string; label: string }[] = [
  { value: "g1", label: "高一" },
  { value: "g2", label: "高二" },
  { value: "g3", label: "高三" },
];

export const REG_STATUS_OPTIONS = [
  { value: "registered", label: "已登记" },
  { value: "reported", label: "已报寄" },
  { value: "cancelled", label: "已取消" },
];
