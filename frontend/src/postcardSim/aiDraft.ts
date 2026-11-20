/**
 * 模拟环境调真实 AI 端点时的「草稿参数」注入。
 *
 * 为什么必须集中在这里：模拟环境保存 AI 配置**只写内存**（绝不落库，避免污染
 * 正式环境），而后端每个 AI 端点都走 `_admin_ai_cfg()`——「已保存的正式配置 +
 * 本次请求里的草稿参数」。所以模拟层每一次真调后端 AI 都必须把内存里的这套
 * 参数带上。以前是每个按钮自己记得塞一遍，漏一个就出事：
 * - 导入海报漏了 → 明明在模拟里配好了 AI，点下去仍报「请先配置AI」；
 * - 用户端 AI 预审漏了 → 每次都静默降级成人工复核。
 * 现在改成 `createSimRequest()` 按**路径**自动注入：以后新增 AI 端点不用再记着，
 * 只要打的是后端 AI 路径就自动带上（漏不了）。
 *
 * 口径与后端 `_ai_overrides()` 对齐：
 * - 空字符串 / 空对象不发，留空 = 沿用已保存的正式配置；
 * - 温度 0 是有效值，必须发（不能用真值判断）；
 * - **不覆盖请求里已有的同名字段**：组件传上来的是「页面上还没保存的草稿」，
 *   那套参数比内存里已保存的更实时，必须是它赢。
 */
import { createRequest } from "../api/shared";
import type { SimAIConfig, SimState } from "./state";

/** 后端这些路径都只认「已保存配置 + 本次草稿」：模拟层一律要补草稿。 */
const AI_PATHS = [/^\/admin\/ai\//, /^\/admin\/schools\/import\//];
/** 只对写请求注入（GET 列表 / 图片下载带上 body 没有意义，还会被当成脏请求）。 */
const MUTATING = new Set(["POST", "PUT", "PATCH"]);

/** 内存里的 AI 配置 → 请求草稿参数（只读，不落库）。 */
export function simAIDraft(ai: SimAIConfig): Record<string, unknown> {
  const draft: Record<string, unknown> = {};
  if (ai.base_url) draft.base_url = ai.base_url;
  if (ai.model) draft.model = ai.model;
  if (ai.timeout_seconds) draft.timeout_seconds = ai.timeout_seconds;
  // 0 是有效值（审核默认最确定），只能判断 undefined / null。
  if (ai.temperature !== undefined && ai.temperature !== null) draft.temperature = ai.temperature;
  if (Object.keys(ai.extra_headers).length) draft.extra_headers = ai.extra_headers;
  if (ai.ip_blacklist.length) draft.ip_blacklist = ai.ip_blacklist;
  if (ai.prompt_prefix) draft.prompt_prefix = ai.prompt_prefix;
  // api_key 只在内存里活着（正式配置的 key 永远读不回来），所以一定要带上。
  if (ai.api_key) draft.api_key = ai.api_key;
  return draft;
}

/**
 * 把草稿填进请求体：FormData 只补缺的键（不覆盖组件传的草稿），
 * JSON 体同理（`{...draft, ...body}`）。两者都补上 `dry_run`（不写审计）。
 */
function injectDraft(options: RequestInit, draft: Record<string, unknown>): RequestInit {
  const { body } = options;
  if (body instanceof FormData) {
    for (const [key, value] of Object.entries(draft)) {
      if (value === undefined || value === null || value === "") continue;
      if (body.has(key)) continue;
      body.set(key, typeof value === "string" ? value : JSON.stringify(value));
    }
    if (!body.has("dry_run")) body.set("dry_run", "1");
    return options;
  }
  if (typeof body === "string") {
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(body) as Record<string, unknown>;
    } catch {
      return options; // 非 JSON 体不猜，交给调用方
    }
    return { ...options, body: JSON.stringify({ ...draft, ...parsed, dry_run: true }) };
  }
  return options;
}

/**
 * 模拟环境的请求器：与 `createRequest()` 同签名，只是给 AI 路径自动补草稿参数。
 *
 * 新增任何「模拟里真跑 AI」的入口都走它，别再各自拼参数——这类漏参数的 bug
 * 已经在导入海报 / 用户端预审上各踩过一次。
 */
export function createSimRequest(state: SimState) {
  const raw = createRequest("/events/postcard");
  return function request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    const method = String(options.method || "GET").toUpperCase();
    const needsDraft = MUTATING.has(method) && AI_PATHS.some((re) => re.test(path));
    return raw<T>(path, needsDraft ? injectDraft(options, simAIDraft(state.ai)) : options);
  };
}
