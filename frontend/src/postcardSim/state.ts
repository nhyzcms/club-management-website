/**
 * 明信片互寄 · 模拟环境的数据模型（纯函数，无 React / DOM / 网络依赖）。
 *
 * 模拟环境（`#/postcard/admin?sim=1`）用一份**内存**状态替代后端：所有 tab 的读写
 * 都落在这里，退出 / 刷新即随模块一起消失（用户要求：模拟数据不与正式环境联动、
 * 退出即清空）。因此这里刻意复刻服务端的判定口径（阶段推导、条码区间、登记状态），
 * 但不复刻数据库约束与限流——模拟是给管理员练手与验收新功能用的。
 *
 * 与后端真源对应关系：
 * - 阶段推导 → events/modules/postcard/state.py 的 `phase_of`
 * - 条码区间 → models.PostcardConfig 的 BARCODE_MIN/MAX/STEP
 * - 登记三态 → models 里的 STATUS_CHOICES
 */
import {
  POSTCARD_GRADES,
  POSTCARD_REGIONS,
  type AdminConfig,
  type AdminConfigInput,
  type AdminSchool,
  type AuditRow,
  type Paged,
  type RecordQuery,
  type RecordRow,
  type StatsPayload,
  type SuggestionRow,
} from "../api/postcardAdmin";
import type {
  PostcardItemSummary,
  PostcardPortal,
  PostcardProgressNode,
  PostcardRegistrationSummary,
  RegisterResult,
} from "../api/postcard";

export const PHASE_LABELS = {
  not_started: "未开始",
  registering: "登记中",
  shipped: "已寄出",
  distributing: "下发中",
  ended: "已结束",
} as const;

export type SimPhase = keyof typeof PHASE_LABELS;

/** 条码硬约束（与后端 models 一致：单活动累计 ≤10000，按 500 递增）。 */
export const BARCODE_MIN = 1500;
export const BARCODE_MAX = 10000;
export const BARCODE_STEP = 500;
export const BARCODE_DEFAULT = 6000;

/** 列表页大小（与后端分页一致）。 */
export const RECORDS_PAGE_SIZE = 20;
export const SIM_PAGE_SIZE = 20;

export type SimEventStatus = "draft" | "published" | "archived";
export type SimRegStatus = "registered" | "reported" | "cancelled";

export const REG_STATUS_LABELS: Record<SimRegStatus, string> = {
  registered: "已登记",
  reported: "已报寄",
  cancelled: "已取消",
};

const GRADE_LABELS: Record<string, string> = Object.fromEntries(
  POSTCARD_GRADES.map((g) => [g.value, g.label]),
);

export interface SimEvent {
  id: number;
  title: string;
  summary: string;
  status: SimEventStatus;
  start_at: string;
  end_at: string | null;
}

export interface SimConfig {
  ship_at: string | null;
  distribute_at: string | null;
  allowed_grades: string[];
  destination_schools: AdminSchool[];
  announcement_body: string;
  has_announcement_pdf: boolean;
}

export interface SimBarcode {
  id: number;
  code: string;
  /** 被哪张登记单占用（null = 还没发出去）。 */
  registration_id: number | null;
}

/**
 * 复核状态（取值与后端 `PostcardPhoto.REVIEW_CHOICES` 逐字一致）：
 * `pending / ai_passed / ai_failed / manual_pending / manual_passed / manual_failed`。
 * 模拟里要照抄这套字符串，否则界面文案与真实环境对不上，教学时会记错。
 */
export type SimReviewState =
  | "pending"
  | "ai_passed"
  | "ai_failed"
  | "manual_pending"
  | "manual_passed"
  | "manual_failed";

export const REVIEW_LABELS: Record<SimReviewState, string> = {
  pending: "待审核",
  ai_passed: "AI 通过",
  ai_failed: "AI 不匹配",
  manual_pending: "待人工复核",
  manual_passed: "人工通过",
  manual_failed: "人工不通过",
};

export interface SimPhoto {
  id: number;
  side: "front" | "back";
  /** 模拟环境的照片就是浏览器里的 data URL，不进任何存储。 */
  data_url: string;
}

export interface SimItem {
  id: number;
  barcode: string;
  status: SimRegStatus;
  review_state: SimReviewState;
  ai_verdict: Record<string, any> | null;
  /** AI 判不匹配的填写项（面向用户的「哪里填错」）。 */
  mismatched: string[];
  comment: string;
  photos: SimPhoto[];
}

export interface SimRegistration {
  id: number;
  reg_code: string;
  /** 服务端权威：这条提交现在是否该亮码（模拟里转人工也立即发码）。 */
  code_granted: boolean;
  /** 轮询凭证（审核中/复核时用；模拟里同样给）。 */
  access_token: string;
  /** 归属三轨之一：浏览器指纹。 */
  fingerprint: string;
  sender_name: string;
  grade: string;
  class_no: number;
  dest_region: string;
  dest_school: string;
  status: SimRegStatus;
  created_at: string;
  updated_at: string;
  items: SimItem[];
}

export interface SimSample {
  id: number;
  caption: string;
  data_url: string;
}

export interface SimAIConfig {
  enabled: boolean;
  base_url: string;
  model: string;
  timeout_seconds: number;
  extra_headers: Record<string, string>;
  ip_blacklist: string[];
  /** 只在内存里活着；除「测试连接」外不外发。 */
  api_key: string;
  api_key_set: boolean;
}

export interface SimState {
  seq: number;
  event: SimEvent | null;
  config: SimConfig | null;
  barcodes: SimBarcode[];
  registrations: SimRegistration[];
  samples: SimSample[];
  ai: SimAIConfig;
  suggestions: SuggestionRow[];
  audit: AuditRow[];
}

/** 模拟环境的错误载体：形状与 `createRequest` 抛出的 ApiError 对齐，文案直接可见。 */
export class SimError extends Error {
  status: number;
  constructor(message: string, status = 400) {
    super(message);
    this.name = "SimError";
    this.status = status;
  }
}

export function emptySimState(): SimState {
  return {
    seq: 1,
    event: null,
    config: null,
    barcodes: [],
    registrations: [],
    samples: [],
    ai: {
      enabled: false,
      base_url: "",
      model: "",
      timeout_seconds: 20,
      extra_headers: {},
      ip_blacklist: [],
      api_key: "",
      api_key_set: false,
    },
    suggestions: [],
    audit: [],
  };
}

function nextId(state: SimState): number {
  const id = state.seq;
  state.seq += 1;
  return id;
}

/** 7 位随机数字条码（活动内唯一）。 */
function randomBarcode(state: SimState): string {
  for (let i = 0; i < 50; i += 1) {
    const code = String(Math.floor(1000000 + Math.random() * 9000000));
    if (!state.barcodes.some((b) => b.code === code)) return code;
  }
  return String(1000000 + state.barcodes.length);
}

/** 6 位登记码。 */
export function randomRegCode(state: SimState): string {
  for (let i = 0; i < 50; i += 1) {
    const code = String(Math.floor(100000 + Math.random() * 900000));
    if (!state.registrations.some((r) => r.reg_code === code)) return code;
  }
  return String(100000 + state.registrations.length);
}

/** 阶段推导（镜像后端 state.py::phase_of，`now` 可注入便于单测）。 */
export function phaseOf(
  event: SimEvent | null,
  config: SimConfig | null,
  now: Date = new Date(),
): SimPhase {
  if (!event || !config) return "not_started";
  if (event.status === "draft") return "not_started";
  if (event.status === "archived") return "ended";
  const t = now.getTime();
  const at = (iso: string | null): number | null => {
    if (!iso) return null;
    const v = new Date(iso).getTime();
    return Number.isNaN(v) ? null : v;
  };
  const start = at(event.start_at);
  const end = at(event.end_at);
  const ship = at(config.ship_at);
  const distribute = at(config.distribute_at);
  if (start !== null && t < start) return "not_started";
  if (distribute !== null && t >= distribute) {
    if (end !== null && t >= end) return "ended";
    return "distributing";
  }
  if (ship !== null && t >= ship) return "shipped";
  if (end !== null && t >= end) return "ended";
  return "registering";
}

/** 管理端配置载荷（GET /admin/config/ 的响应形状）。 */
export function configPayload(state: SimState, now: Date = new Date()): AdminConfig {
  const phase = phaseOf(state.event, state.config, now);
  const event = state.event;
  return {
    configured: Boolean(event && state.config),
    phase,
    phase_label: PHASE_LABELS[phase],
    event: event
      ? {
          id: event.id,
          title: event.title,
          summary: event.summary,
          status: event.status,
          start_at: event.start_at,
          end_at: event.end_at,
        }
      : null,
    announcement_body: state.config?.announcement_body ?? "",
    has_announcement_pdf: state.config?.has_announcement_pdf ?? false,
    allowed_grades: state.config?.allowed_grades ?? POSTCARD_GRADES.map((g) => g.value),
    destination_schools: state.config?.destination_schools ?? [],
    ship_at: state.config?.ship_at ?? null,
    distribute_at: state.config?.distribute_at ?? null,
    barcode_count: state.barcodes.length,
    registration_count: state.registrations.length,
  };
}

/** 保存活动配置：草稿可改壳字段；已开始只允许改节点 / 学校 / 公告（与后端一致）。 */
export function saveConfig(
  state: SimState,
  input: AdminConfigInput,
  opts: { pdf?: File | null; clearPdf?: boolean } = {},
  now: Date = new Date(),
): AdminConfig {
  const phase = phaseOf(state.event, state.config, now);
  const started = phase !== "not_started" && state.event?.status !== "draft";
  if (started && state.event) {
    // 与后端 AdminConfigView 一致：壳字段 = 标题 / 简介 / 起止时间（2026-11-09 补齐 summary）。
    const shellChanged =
      input.title !== state.event.title
      || (input.summary || "") !== state.event.summary
      || input.start_at !== state.event.start_at
      || (input.end_at || null) !== state.event.end_at;
    if (shellChanged) {
      throw new SimError("活动已开始，标题 / 起止时间由服务端锁定，只能修改节点、学校与公告。");
    }
  }
  if (!input.title.trim()) throw new SimError("活动标题不能为空。");
  if (!input.start_at || !input.end_at) throw new SimError("请填写登记开始与活动结束时间。");
  if (input.allowed_grades.length === 0) throw new SimError("请至少选择一个可参与年级。");

  const event: SimEvent = state.event ?? {
    id: nextId(state),
    title: "",
    summary: "",
    status: "draft",
    start_at: input.start_at,
    end_at: input.end_at,
  };
  event.title = input.title.trim();
  event.summary = input.summary.trim();
  event.start_at = input.start_at;
  event.end_at = input.end_at;
  state.event = event;

  const config: SimConfig = state.config ?? {
    ship_at: null,
    distribute_at: null,
    allowed_grades: [],
    destination_schools: [],
    announcement_body: "",
    has_announcement_pdf: false,
  };
  config.ship_at = input.ship_at || null;
  config.distribute_at = input.distribute_at || null;
  config.allowed_grades = [...input.allowed_grades];
  config.destination_schools = input.destination_schools.map((s) => ({ ...s }));
  config.announcement_body = input.body;
  if (opts.clearPdf) config.has_announcement_pdf = false;
  if (opts.pdf) config.has_announcement_pdf = true;
  state.config = config;

  pushAudit(state, "config_save", `event:${event.id}`, {
    title: event.title,
    schools: config.destination_schools.length,
    pdf: config.has_announcement_pdf,
  });
  return configPayload(state, now);
}

/** 发布活动（草稿 → 已发布；阶段仍按时间推导）。 */
export function publish(state: SimState): void {
  if (!state.event || !state.config) throw new SimError("请先保存活动配置。");
  if (state.event.status !== "draft") throw new SimError("活动已发布。");
  state.event.status = "published";
  pushAudit(state, "publish", `event:${state.event.id}`, {});
}

/** 开启新一届：归档当前 + 新建草稿，复制年级与学校清单。 */
export function newSeason(state: SimState): { event_id: number; previous_event: number | null } {
  const previous = state.event ? state.event.id : null;
  if (state.event) state.event.status = "archived";
  const id = nextId(state);
  state.event = {
    id,
    title: "",
    summary: "",
    status: "draft",
    start_at: "",
    end_at: null,
  };
  state.config = {
    ship_at: null,
    distribute_at: null,
    allowed_grades: [...(state.config?.allowed_grades ?? [])],
    destination_schools: (state.config?.destination_schools ?? []).map((s) => ({ ...s })),
    announcement_body: "",
    has_announcement_pdf: false,
  };
  // 新一届从零开始发条码：旧条码属于上一届。
  state.barcodes = [];
  state.registrations = [];
  pushAudit(state, "new_season", `event:${id}`, { previous_event: previous });
  return { event_id: id, previous_event: previous };
}

/** 归档当前活动。 */
export function archiveSeason(state: SimState): void {
  if (!state.event) throw new SimError("还没有活动可归档。");
  state.event.status = "archived";
  pushAudit(state, "archive", `event:${state.event.id}`, {});
}

/** 条码概览（GET /admin/barcodes/）。 */
export function barcodeSummary(state: SimState) {
  const bound = state.barcodes.filter((b) => b.registration_id !== null).length;
  return {
    configured: Boolean(state.event && state.config),
    total: state.barcodes.length,
    bound,
    min: BARCODE_MIN,
    max: BARCODE_MAX,
    step: BARCODE_STEP,
    default: BARCODE_DEFAULT,
  };
}

export function generateBarcodes(
  state: SimState,
  count: number,
  replace = false,
): { generated: number; total: number; replaced: boolean } {
  if (!state.event || !state.config) throw new SimError("请先保存活动配置。");
  const bound = state.barcodes.filter((b) => b.registration_id !== null).length;
  if (replace && bound > 0) {
    throw new SimError(`已有 ${bound} 个条码被登记占用，不能覆盖重建。`);
  }
  const n = Math.min(
    BARCODE_MAX,
    Math.max(BARCODE_MIN, Math.round(count / BARCODE_STEP) * BARCODE_STEP),
  );
  if (!replace && state.barcodes.length + n > BARCODE_MAX) {
    throw new SimError(`单活动累计不超过 ${BARCODE_MAX} 个条码。`);
  }
  if (replace) state.barcodes = [];
  for (let i = 0; i < n; i += 1) {
    state.barcodes.push({ id: nextId(state), code: randomBarcode(state), registration_id: null });
  }
  pushAudit(state, replace ? "barcodes_replace" : "barcodes_generate", "barcodes", {
    generated: n,
    total: state.barcodes.length,
  });
  return { generated: n, total: state.barcodes.length, replaced: replace };
}

/** 登记记录平铺（一条登记单的每张明信片各占一行，与后端分页口径一致）。 */
export function recordsPage(state: SimState, query: RecordQuery): Paged<RecordRow> {
  const q = (query.q || "").trim().toLowerCase();
  const rows: RecordRow[] = [];
  for (const reg of state.registrations) {
    for (const item of reg.items) {
      if (q) {
        const hay = `${reg.sender_name} ${reg.reg_code} ${item.barcode}`.toLowerCase();
        if (!hay.includes(q)) continue;
      }
      if (query.grade && reg.grade !== query.grade) continue;
      if (query.class_no && String(reg.class_no) !== String(query.class_no)) continue;
      if (query.region && reg.dest_region !== query.region) continue;
      if (query.school && !reg.dest_school.includes(query.school)) continue;
      if (query.status && reg.status !== query.status) continue;
      if (query.item_status && item.status !== query.item_status) continue;
      rows.push({
        item_id: item.id,
        barcode: item.barcode,
        item_status: item.status,
        item_status_label: REG_STATUS_LABELS[item.status],
        registration: {
          registration_id: reg.id,
          reg_code: reg.reg_code,
          sender_name: reg.sender_name,
          grade: reg.grade,
          grade_label: GRADE_LABELS[reg.grade] || reg.grade,
          class_no: reg.class_no,
          dest_region: reg.dest_region,
          dest_school: reg.dest_school,
          status: reg.status,
          status_label: REG_STATUS_LABELS[reg.status],
          created_at: reg.created_at,
        },
      });
    }
  }
  rows.sort((a, b) => (a.registration.created_at < b.registration.created_at ? 1 : -1));
  const page = Math.max(1, query.page ?? 1);
  const start = (page - 1) * RECORDS_PAGE_SIZE;
  return {
    count: rows.length,
    next: start + RECORDS_PAGE_SIZE < rows.length ? String(page + 1) : null,
    previous: page > 1 ? String(page - 1) : null,
    results: rows.slice(start, start + RECORDS_PAGE_SIZE),
  };
}

export function statsOf(state: SimState): StatsPayload {
  const regs = state.registrations;
  const items = regs.flatMap((r) => r.items);
  const regCount = (status: SimRegStatus) => regs.filter((r) => r.status === status).length;
  const itemCount = (status: SimRegStatus) => items.filter((i) => i.status === status).length;

  const schoolMap = new Map<string, { school: string; total: number; reported: number }>();
  for (const r of regs) {
    const key = r.dest_school || "";
    const cur = schoolMap.get(key) ?? { school: key, total: 0, reported: 0 };
    cur.total += r.items.length;
    cur.reported += r.items.filter((i) => i.status === "reported").length;
    schoolMap.set(key, cur);
  }
  const gradeMap = new Map<string, number>();
  for (const r of regs) gradeMap.set(r.grade, (gradeMap.get(r.grade) ?? 0) + r.items.length);
  const dayMap = new Map<string, number>();
  for (const r of regs) {
    const day = r.created_at.slice(0, 10);
    dayMap.set(day, (dayMap.get(day) ?? 0) + r.items.length);
  }

  return {
    registrations: {
      total: regs.length,
      registered: regCount("registered"),
      reported: regCount("reported"),
      cancelled: regCount("cancelled"),
    },
    items: {
      total: items.length,
      registered: itemCount("registered"),
      reported: itemCount("reported"),
      cancelled: itemCount("cancelled"),
    },
    destination_schools: new Set(regs.map((r) => r.dest_school).filter(Boolean)).size,
    by_school: [...schoolMap.values()].sort((a, b) => b.total - a.total),
    by_grade: [...gradeMap.entries()].map(([grade, total]) => ({ grade, total })),
    by_day: [...dayMap.entries()]
      .sort(([a], [b]) => (a < b ? -1 : 1))
      .map(([day, total]) => ({ day, total })),
  };
}

function pageOf<T>(rows: T[], page: number): Paged<T> {
  const p = Math.max(1, page);
  const start = (p - 1) * SIM_PAGE_SIZE;
  return {
    count: rows.length,
    next: start + SIM_PAGE_SIZE < rows.length ? String(p + 1) : null,
    previous: p > 1 ? String(p - 1) : null,
    results: rows.slice(start, start + SIM_PAGE_SIZE),
  };
}

/** 建议箱（模拟里一般为空；用户端提交建议后进这里，PR2 接上）。 */
export function suggestionsPage(state: SimState, page: number): Paged<SuggestionRow> {
  return pageOf([...state.suggestions].reverse(), page);
}

export function auditPage(state: SimState, page: number): Paged<AuditRow> {
  return pageOf([...state.audit].reverse(), page);
}

/** 写一条审计（模拟环境的审计是「教学回放」，user / ip 固定标注来源）。 */
export function pushAudit(
  state: SimState,
  action: string,
  target: string,
  detail: Record<string, any> | null,
  now: Date = new Date(),
): void {
  state.audit.push({
    id: nextId(state),
    action,
    target,
    detail,
    user: "模拟环境",
    ip: "—",
    created_at: now.toISOString(),
  });
}

/** 取一条登记单（按单份提交 id）。 */
export function findRegistration(state: SimState, registrationId: number): SimRegistration | null {
  return state.registrations.find((r) => r.id === registrationId) ?? null;
}

/** 改登记单（状态改动同步到该单所有明信片，与后端整单口径一致）。 */
export function updateRegistration(
  state: SimState,
  registrationId: number,
  patch: Partial<{
    sender_name: string;
    grade: string;
    class_no: number;
    dest_region: string;
    dest_school: string;
    status: string;
  }>,
): { reg_code: string } {
  const reg = findRegistration(state, registrationId);
  if (!reg) throw new SimError("登记单不存在。", 404);
  if (patch.sender_name !== undefined) {
    if (!patch.sender_name.trim()) throw new SimError("寄出人姓名不能为空。");
    reg.sender_name = patch.sender_name.trim();
  }
  if (patch.grade !== undefined) reg.grade = patch.grade;
  if (patch.class_no !== undefined) reg.class_no = Number(patch.class_no);
  if (patch.dest_region !== undefined) reg.dest_region = patch.dest_region;
  if (patch.dest_school !== undefined) reg.dest_school = patch.dest_school.trim();
  if (patch.status !== undefined) {
    const status = patch.status as SimRegStatus;
    if (!(status in REG_STATUS_LABELS)) throw new SimError("状态不合法。");
    reg.status = status;
    for (const item of reg.items) item.status = status;
  }
  pushAudit(state, "registration_update", `registration:${reg.id}`, { ...patch });
  return { reg_code: reg.reg_code };
}

/**
 * 按条目联动登记单状态（镜像后端 `PostcardRegistration.sync_status_from_items`）：
 * **全部未取消的条目**都报寄 → 登记单「已报寄」，否则「已登记」；已取消的单不动。
 */
export function syncRegistrationStatus(reg: SimRegistration): void {
  if (reg.status === "cancelled") return;
  const active = reg.items.filter((it) => it.status !== "cancelled");
  const allReported = active.length > 0 && active.every((it) => it.status === "reported");
  reg.status = allReported ? "reported" : "registered";
}

export function deleteRegistration(state: SimState, registrationId: number): void {
  const reg = findRegistration(state, registrationId);
  if (!reg) throw new SimError("登记单不存在。", 404);
  for (const item of reg.items) {
    const slot = state.barcodes.find((b) => b.code === item.barcode);
    if (slot) slot.registration_id = null;
  }
  state.registrations = state.registrations.filter((r) => r.id !== registrationId);
  pushAudit(state, "registration_delete", `registration:${reg.id}`, { reg_code: reg.reg_code });
}

// ——————————————————————————————————————————————————————————————
// 用户侧（PR2）：portal / 登记 / 历史 / 查询 / 改 / 取消 / 申请复核 / 建议
// ——————————————————————————————————————————————————————————————

/** 模拟环境的「AI 是否可用」：配置齐了才算，与后端的 ready 口径一致。 */
export function aiReady(state: SimState): boolean {
  return Boolean(state.ai.enabled && state.ai.base_url && state.ai.model && state.ai.api_key_set);
}

function progressOf(state: SimState, now: Date): PostcardProgressNode[] {
  const event = state.event;
  const config = state.config;
  if (!event || !config) return [];
  const nodes: { key: string; label: string; time: string | null }[] = [
    { key: "start", label: "登记开始", time: event.start_at || null },
    { key: "ship", label: "已寄出", time: config.ship_at },
    { key: "distribute", label: "下发中", time: config.distribute_at },
    { key: "end", label: "活动结束", time: event.end_at },
  ];
  return nodes.map((n) => ({
    ...n,
    reached: Boolean(n.time && now.getTime() >= new Date(n.time).getTime()),
  }));
}

/** 一站式状态（GET /portal/）。用户端只认「登记中」可填，其余阶段只读。 */
export function portalOf(state: SimState, now: Date = new Date()): PostcardPortal {
  const phase = phaseOf(state.event, state.config, now);
  const event = state.event;
  return {
    phase,
    phase_label: PHASE_LABELS[phase],
    // 模拟环境跳过「必须先上传填写样例」的门禁，否则练手前还要先造一张样例图。
    can_register: phase === "registering",
    is_admin: true,
    sample_ready: state.samples.length > 0,
    event: event
      ? {
          id: event.id,
          title: event.title,
          summary: event.summary,
          start_at: event.start_at,
          end_at: event.end_at,
        }
      : null,
    progress: progressOf(state, now),
    grades: (state.config?.allowed_grades ?? POSTCARD_GRADES.map((g) => g.value)).map((value) => ({
      value,
      label: GRADE_LABELS[value] || value,
    })),
    classes: Array.from({ length: 8 }, (_, i) => i + 1),
    regions: [...POSTCARD_REGIONS],
    schools: (state.config?.destination_schools ?? []).map((s) => ({ ...s })),
    announcement_body: state.config?.announcement_body ?? "",
    announcement_pdf: Boolean(state.config?.has_announcement_pdf),
  };
}

function maskedCode(code: string): string {
  return code.length >= 2 ? `${code.slice(0, 2)}****` : "****";
}

function itemSummary(item: SimItem): PostcardItemSummary {
  return {
    id: item.id,
    barcode: item.barcode,
    status: item.status,
    status_label: REG_STATUS_LABELS[item.status],
    review_state: item.review_state,
    review_label: REVIEW_LABELS[item.review_state],
    mismatched: [...item.mismatched],
    comment: item.comment,
    // 照片只在「还留着」时下发（通过后服务端会删，模拟里同步删掉）。
    photos: item.photos.map((p) => ({ id: p.id, side: p.side })),
  };
}

/** 登记单摘要（`mask=true` 时按姓名查询的口径：掩码 + 无照片，改不了）。 */
export function registrationSummary(
  reg: SimRegistration,
  opts: { mask?: boolean } = {},
): PostcardRegistrationSummary {
  const mask = Boolean(opts.mask) || !reg.code_granted;
  return {
    id: reg.id,
    reg_code: mask ? maskedCode(reg.reg_code) : reg.reg_code,
    code_granted: reg.code_granted,
    access_token: mask ? undefined : reg.access_token,
    sender_name: reg.sender_name,
    grade: reg.grade,
    grade_label: GRADE_LABELS[reg.grade] || reg.grade,
    class_no: reg.class_no,
    dest_region: reg.dest_region,
    dest_school: reg.dest_school,
    status: reg.status,
    status_label: REG_STATUS_LABELS[reg.status],
    created_at: reg.created_at,
    updated_at: reg.updated_at,
    items: reg.items.map((it) => {
      const s = itemSummary(it);
      return mask ? { ...s, photos: [] } : s;
    }),
  };
}

export interface SubmitItemInput {
  barcode: string;
  photos: { side: "front" | "back"; data_url: string }[];
}

export interface SubmitRegistrationInput {
  sender_name: string;
  grade: string;
  class_no: number;
  dest_region: string;
  dest_school: string;
  fingerprint: string;
  items: SubmitItemInput[];
}

/**
 * 提交登记（POST /register/）。
 *
 * 模拟环境的口径：AI 配齐 → 直接判通过（照片随即删除，登记码立即发放）；
 * AI 没配 → 转人工复核（**同样立即发码**，与用户 2026-11-08 定的规则一致），
 * 这样管理员还能顺带把审核台那条链路走一遍。
 */
export function submitRegistration(
  state: SimState,
  input: SubmitRegistrationInput,
  now: Date = new Date(),
): RegisterResult {
  const phase = phaseOf(state.event, state.config, now);
  if (phase !== "registering") throw new SimError("当前不在登记阶段，无法提交登记。");
  if (!input.sender_name.trim()) throw new SimError("寄出人姓名不能为空。");
  if (!input.grade) throw new SimError("请选择年级。");
  if (!input.class_no) throw new SimError("请选择班级。");
  if (!input.dest_region || !input.dest_school.trim()) throw new SimError("请选择寄达区与寄达校。");
  const config = state.config;
  const allowed = config?.allowed_grades ?? [];
  if (allowed.length && !allowed.includes(input.grade)) throw new SimError("该年级不在本次活动范围内。");
  const schools = config?.destination_schools ?? [];
  if (schools.length && !schools.some((s) => s.region === input.dest_region && s.name === input.dest_school.trim())) {
    throw new SimError("寄达校不在本次活动清单里。");
  }
  if (input.items.length === 0) throw new SimError("请至少添加一张明信片。");
  if (input.items.length > 5) throw new SimError("一次最多提交 5 张明信片。");

  for (const it of input.items) {
    const slot = state.barcodes.find((b) => b.code === it.barcode);
    if (!slot) throw new SimError(`条码 ${it.barcode} 不在本次活动里，请核对后再填。`);
    if (slot.registration_id !== null) throw new SimError(`条码 ${it.barcode} 已被登记，不能重复使用。`);
  }

  const ready = aiReady(state);
  const regId = nextId(state);
  const nowIso = now.toISOString();
  // 「同一发件人」= 姓名 + 年级 + 班级（用户 2026-11-08 定的口径）：复用同一登记码，
  // 但每次提交都是**独立的一条登记单**（真实环境就是这么存的，取消/改也按单来）。
  const samePerson = state.registrations.find(
    (r) =>
      r.sender_name === input.sender_name.trim()
      && r.grade === input.grade
      && r.class_no === Number(input.class_no),
  );
  const reg: SimRegistration = {
    id: regId,
    reg_code: samePerson ? samePerson.reg_code : randomRegCode(state),
    code_granted: true,
    access_token: `sim-${regId}-${Math.random().toString(36).slice(2, 10)}`,
    fingerprint: input.fingerprint,
    sender_name: input.sender_name.trim(),
    grade: input.grade,
    class_no: Number(input.class_no),
    dest_region: input.dest_region,
    dest_school: input.dest_school.trim(),
    status: "registered",
    created_at: nowIso,
    updated_at: nowIso,
    items: input.items.map((it) => {
      const slot = state.barcodes.find((b) => b.code === it.barcode);
      if (slot) slot.registration_id = regId;
      return {
        id: nextId(state),
        barcode: it.barcode,
        status: "registered",
        review_state: ready ? "ai_passed" : "manual_pending",
        ai_verdict: ready
          ? { matched: true, mismatched: [], blacklist: [], comment: "模拟环境：AI 视为通过" }
          : null,
        mismatched: [],
        comment: "",
        // 通过即删照片（模拟里也遵守这条生命周期，教学时才不会记错）。
        photos: ready
          ? []
          : it.photos.map((p) => ({ id: nextId(state), side: p.side, data_url: p.data_url })),
      };
    }),
  };
  state.registrations.push(reg);
  pushAudit(state, "register", `registration:${reg.id}`, {
    items: reg.items.length,
    review: ready ? "ai" : "manual",
  }, now);

  const state0: SimReviewState = ready ? "ai_passed" : "manual_pending";
  return {
    reg_code: reg.reg_code,
    code_granted: true,
    access_token: reg.access_token,
    message: ready
      ? "登记成功，照片已按规则删除。"
      : "登记成功。当前未配置 AI 审核，已转人工复核。",
    registration: registrationSummary(reg),
    review: {
      state: state0,
      hint: ready ? "AI 审核通过" : "等待管理员人工复核",
    },
  };
}

/** 历史登记（GET /my/）：按指纹归属。 */
export function myRegistrations(state: SimState, fingerprint: string): PostcardRegistrationSummary[] {
  return state.registrations
    .filter((r) => !fingerprint || r.fingerprint === fingerprint)
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    .map((r) => registrationSummary(r));
}

/** 同一登记码可能对应多份提交（一条提交一条记录，与后端一致）。 */
export function findRegistrationsByCode(state: SimState, regCode: string): SimRegistration[] {
  return state.registrations.filter((r) => r.reg_code === regCode);
}

export function findRegistrationByCode(state: SimState, regCode: string): SimRegistration | null {
  return findRegistrationsByCode(state, regCode)[0] ?? null;
}

export function findRegistrationByToken(state: SimState, token: string): SimRegistration | null {
  return state.registrations.find((r) => r.access_token === token) ?? null;
}

/** 用户侧查询（POST /lookup/）：6 位码 → 完整；姓名 → 掩码列表。 */
export function lookupRegistrations(
  state: SimState,
  q: string,
): { kind: "code" | "name"; results: PostcardRegistrationSummary[] } {
  const query = q.trim();
  if (!query) throw new SimError("请输入登记码或寄出人姓名。");
  if (/^\d{6}$/.test(query)) {
    const hits = findRegistrationsByCode(state, query);
    if (hits.length === 0) throw new SimError("没有找到这个登记码，请核对。");
    return { kind: "code", results: hits.map((r) => registrationSummary(r)) };
  }
  const hits = state.registrations.filter((r) => r.sender_name.includes(query));
  if (hits.length === 0) throw new SimError("没有找到对应的登记记录。");
  return { kind: "name", results: hits.map((r) => registrationSummary(r, { mask: true })) };
}

/** 改自己的登记（仅寄出人信息；条码与照片不可改）。 */
export function updateOwnRegistration(
  state: SimState,
  regCode: string,
  patch: Partial<Pick<SimRegistration, "sender_name" | "grade" | "class_no" | "dest_region" | "dest_school">>,
  submissionId?: number,
  now: Date = new Date(),
): PostcardRegistrationSummary {
  const regs = findRegistrationsByCode(state, regCode);
  if (regs.length === 0) throw new SimError("登记单不存在或登记码有误。", 404);
  if (!submissionId && regs.length > 1) {
    // 后端同款：一个码下多份提交时必须指定 `id`，否则不知道该改哪一份。
    throw new SimError("该登记码对应多份提交，请指定要修改的提交（id）。");
  }
  const reg = submissionId ? regs.find((r) => r.id === submissionId) : regs[0];
  if (!reg) throw new SimError("这条提交不存在。", 404);
  if (reg.status === "cancelled") throw new SimError("已取消的登记不能修改。");

  const config = state.config;
  if (patch.grade !== undefined) {
    const allowed = config?.allowed_grades ?? [];
    if (allowed.length && !allowed.includes(patch.grade)) {
      throw new SimError("你的年级不在本次活动可参与范围内。");
    }
    reg.grade = patch.grade;
  }
  if (patch.dest_region !== undefined) {
    if (!POSTCARD_REGIONS.includes(patch.dest_region)) throw new SimError("寄达区不在支持范围内。");
    reg.dest_region = patch.dest_region;
  }
  if (patch.dest_school !== undefined) {
    const schools = config?.destination_schools ?? [];
    const name = patch.dest_school.trim();
    if (schools.length && !schools.some((s) => s.region === (patch.dest_region ?? reg.dest_region) && s.name === name)) {
      throw new SimError("寄达校不在本次活动支持的学校清单内。");
    }
    reg.dest_school = name;
  }
  if (patch.sender_name !== undefined) {
    if (!patch.sender_name.trim()) throw new SimError("寄出人姓名不能为空。");
    reg.sender_name = patch.sender_name.trim();
  }
  if (patch.class_no !== undefined) reg.class_no = Number(patch.class_no);
  reg.updated_at = now.toISOString();
  pushAudit(state, "my_update", `registration:${reg.id}`, { ...patch }, now);
  return registrationSummary(reg);
}

/** 取消登记（scope=one 只撤该份提交；all 撤该码下全部）。不可恢复。 */
export function cancelOwnRegistration(
  state: SimState,
  regCode: string,
  scope: "one" | "all" = "one",
  submissionId?: number,
  now: Date = new Date(),
): PostcardRegistrationSummary {
  const regs = findRegistrationsByCode(state, regCode);
  if (regs.length === 0) throw new SimError("登记单不存在或登记码有误。", 404);
  const targets =
    scope === "all"
      ? regs
      : [submissionId ? regs.find((r) => r.id === submissionId) : regs[0]].filter(
          (r): r is SimRegistration => Boolean(r),
        );
  if (targets.length === 0) throw new SimError("这条提交不存在。", 404);
  const changed = targets.filter((r) => r.status !== "cancelled");
  if (changed.length === 0) throw new SimError("该登记已是取消状态。");
  for (const reg of changed) {
    // 后端 cancel：整条提交（含其全部条目）一起作废。
    reg.status = "cancelled";
    for (const it of reg.items) it.status = "cancelled";
    reg.updated_at = now.toISOString();
    pushAudit(state, "my_cancel", `registration:${reg.id}`, { scope, submissionId }, now);
  }
  return registrationSummary(changed[0]);
}

/** 判不匹配 → 申请人工复核（转 manual_pending 并保持发码）。 */
export function requestManualReview(
  state: SimState,
  opts: { regCode?: string; token?: string },
  now: Date = new Date(),
): { message: string; count: number } {
  const regs = opts.regCode
    ? findRegistrationsByCode(state, opts.regCode)
    : opts.token
      ? [findRegistrationByToken(state, opts.token)].filter((r): r is SimRegistration => Boolean(r))
      : [];
  if (regs.length === 0) throw new SimError("登记单不存在。", 404);
  let count = 0;
  for (const reg of regs) {
    for (const it of reg.items) {
      // 后端只把 ai_failed 翻成 manual_pending（manual_failed / pending 不在此列）。
      if (it.review_state === "ai_failed") {
        it.review_state = "manual_pending";
        count += 1;
      }
    }
  }
  if (count === 0) throw new SimError("当前没有 AI 判定不匹配、需要人工复核的明信片。");
  pushAudit(state, "my_review_request", `registration:${regs[0].id}`, { count }, now);
  return { message: "已提交人工复核，请耐心等待复核结果", count };
}

/** 照片下发（模拟里直接给 data URL；找不到给空串，<img> 会显示裂图）。 */
export function photoDataUrl(state: SimState, photoId: number): string {
  for (const reg of state.registrations) {
    for (const item of reg.items) {
      const hit = item.photos.find((p) => p.id === photoId);
      if (hit) return hit.data_url;
    }
  }
  return "";
}

/** 用户提交建议 → 进管理端的「建议与审计」tab。 */
export function addSuggestion(
  state: SimState,
  content: string,
  contact: string,
  now: Date = new Date(),
): void {
  if (!content.trim()) throw new SimError("建议内容不能为空。");
  state.suggestions.push({
    id: nextId(state),
    content: content.trim(),
    contact: contact.trim(),
    created_at: now.toISOString(),
  });
}
