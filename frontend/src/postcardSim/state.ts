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

export interface SimItem {
  id: number;
  barcode: string;
  status: SimRegStatus;
  /** 复核状态（模拟环境里只有管理员复核写的判定）。 */
  review_state: "none" | "manual_pending" | "ai_failed" | "approved" | "rejected";
  ai_verdict: Record<string, any> | null;
  /** 照片（data URL），只存在内存，刷新即丢。 */
  photos: string[];
}

export interface SimRegistration {
  id: number;
  reg_code: string;
  sender_name: string;
  grade: string;
  class_no: number;
  dest_region: string;
  dest_school: string;
  status: SimRegStatus;
  created_at: string;
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
    const shellChanged =
      input.title !== state.event.title
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
