/**
 * 管理端纯函数（无 React / DOM 依赖，单测直接覆盖）。
 */

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** ISO 时间串 → `<input type="datetime-local">` 的本地值（空值返回 ""）。 */
export function isoToLocalInput(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** datetime-local 值 → 带时区的 ISO（浏览器按本地时区解释，服务端收到绝对时间）。 */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

/** 统一错误文案：后端 detail / 校验字段错误 / 网络异常都能落成一句人话。 */
export function errMessage(e: unknown): string {
  const anyErr = e as { message?: string; status?: number; apiError?: { kind?: string } };
  if (anyErr?.apiError?.kind === "network") return "网络异常，请稍后重试。";
  if (anyErr?.apiError?.kind === "forbidden") return "没有权限执行该操作。";
  if (typeof anyErr?.message === "string" && anyErr.message.trim()) return anyErr.message;
  if (typeof anyErr?.status === "number" && anyErr.status > 0) return `请求失败（${anyErr.status}）`;
  return "操作失败，请稍后重试。";
}

export function isForbidden(e: unknown): boolean {
  return (e as { apiError?: { kind?: string } })?.apiError?.kind === "forbidden";
}

export interface VerdictSummary {
  matched: boolean | null;
  mismatched: string[];
  blacklist: string[];
  comment: string;
  manual: string;
}

/** AI 判定（或人工改判后的复合判定）→ 复核台展示用摘要。 */
export function verdictSummary(verdict: unknown): VerdictSummary | null {
  if (!verdict || typeof verdict !== "object") return null;
  const raw = verdict as Record<string, any>;
  // 人工判定后 ai_verdict 结构变成 { manual: {...}, ai_verdict: {...} }，原判定仍保留。
  const manual = raw.manual && typeof raw.manual === "object" ? raw.manual : null;
  const ai = manual ? (raw.ai_verdict ?? {}) : raw;
  const list = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  const manualText = manual
    ? `${manual.decision === "pass" ? "人工通过" : "人工不通过"}${manual.note ? `：${manual.note}` : ""}`
    : "";
  return {
    matched: typeof ai.matched === "boolean" ? ai.matched : null,
    mismatched: list(ai.mismatched_items),
    blacklist: list(ai.blacklist_names),
    comment: typeof ai.comment === "string" ? ai.comment : "",
    manual: manualText,
  };
}

/** ISO → `2026-11-08 13:05`（空值给占位符）。 */
export function fmtTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** 条码生成数量：夹在 [min, max] 且对齐步进（前端只是体验，服务端强校验）。 */
export function clampBarcodeCount(value: number, min: number, max: number, step: number): number {
  if (!Number.isFinite(value)) return min;
  const clamped = Math.min(max, Math.max(min, Math.round(value)));
  return min + Math.round((clamped - min) / step) * step;
}

export interface SchoolEntry {
  region: string;
  name: string;
  /** 区内编号（「浦东新区1」→ 1）；老清单可能缺失（排在该区末尾）。 */
  no?: number | null;
}

/** 寄达校清单按区聚组：保持 16 区固定顺序，区内按编号升序（无编号排末尾）。 */
export function groupSchools(
  schools: SchoolEntry[],
  regions: string[],
): { region: string; schools: SchoolEntry[] }[] {
  return regions
    .map((region) => ({
      region,
      schools: schools
        .filter((s) => s.region === region)
        .sort((a, b) => {
          const an = typeof a.no === "number" ? a.no : Number.POSITIVE_INFINITY;
          const bn = typeof b.no === "number" ? b.no : Number.POSITIVE_INFINITY;
          if (an !== bn) return an - bn;
          return a.name.localeCompare(b.name, "zh-Hans-CN");
        }),
    }))
    .filter((g) => g.schools.length > 0);
}

/**
 * 合并「导入海报」的识别结果：同区同名视为同一所（编号以识别结果为准），
 * 其余追加。返回新的清单与新增条数（提示文案要用），不改入参。
 */
export function mergeSchools(
  current: SchoolEntry[],
  incoming: SchoolEntry[],
): { schools: SchoolEntry[]; added: number } {
  const next = current.map((s) => ({ ...s }));
  let added = 0;
  for (const inc of incoming) {
    const i = next.findIndex((s) => s.region === inc.region && s.name === inc.name);
    if (i >= 0) {
      if (typeof inc.no === "number") next[i] = { ...next[i], no: inc.no };
      continue;
    }
    next.push({ region: inc.region, name: inc.name, no: inc.no });
    added += 1;
  }
  return { schools: next, added };
}
