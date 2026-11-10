// 各 api 模块共用的请求工具 —— HTTP 适配器（架构深化 #2，见 #7 / #13 / #16）。
//
// 独占 fetch、鉴权/会话头（credentials）、CSRF，以及单一「HTTP 响应 → 类型化结果」
// 映射（classifyHttpResponse / readResponse）。会话/挤号契约以类型化结果联合
// （ApiError）产出，守卫与弹窗按 kind 分支，不再匹配后端 reason 字符串。

// ---- 命名会话/错误契约（discriminated union）----

/** 挤号接管方信息（后端 takeover 载荷；形状由 accounts 测试 #10 钉死）。 */
export interface SupersedeTakeover {
  device_name?: string;
  device_type?: string;
  ip?: string | null;
  time?: string;
}

/** 适配器产出的类型化错误/会话结果：消费方按 kind 分支，不读后端 reason 串。 */
export type ApiError =
  | {
      kind: "session_superseded";
      takeover: SupersedeTakeover;
      /** 被下线的原因（ADR-0028 多端登录）：limit 名额顶替 / manual 手动下线 / … */
      revokedReason?: string;
    }
  | { kind: "login_protection"; retryAfter: number }
  | { kind: "login_throttled"; retryAfter: number }
  | { kind: "account_disabled" }            // 账号已停用（自助注册三态之一）
  | { kind: "email_not_verified"; email: string }  // 邮箱未认证，登录被拒（提示重发）
  | { kind: "email_domain_not_allowed"; domain: string }  // 邮箱后缀不在白名单（ADR-0023）
  | { kind: "account_exists"; field: string }  // 注册查重命中（用户名/邮箱/真实姓名）
  | { kind: "account_deleted" }      // 命中的是已注销账号
  | { kind: "password_change_required" }  // 管理员重置后必须先改密
  | { kind: "network" }              // 断网 / 超时 / 响应非 JSON
  | { kind: "auth" }                 // 401（非挤号）
  | { kind: "forbidden" }            // 403
  | { kind: "not_found" }            // 404
  | { kind: "http"; status: number }; // 其余非 2xx（400 / 409 / 5xx …）

/** 「会话被挤下线」类型化结果（会话守卫按此消费，不读 reason 串）。 */
export type SessionSupersededResult = Extract<ApiError, { kind: "session_superseded" }>;

/** readResponse 的结果：成功（带数据）或失败（带类型化错误 + 人类可读 message）。 */
type ResponseOutcome<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError; message: string };

// 后端 reason 串常量：reason → kind 的映射只发生在 classifyHttpResponse 一处，
// 后端改字段名时只改这一处（#7 故事 9）。
export const REASON = {
  SESSION_SUPERSEDED: "session_superseded",
  LOGIN_PROTECTION: "login_protection",
  LOGIN_THROTTLED: "login_throttled",
  ACCOUNT_DISABLED: "account_disabled",
  EMAIL_NOT_VERIFIED: "email_not_verified",
  EMAIL_DOMAIN_NOT_ALLOWED: "email_domain_not_allowed",
  ACCOUNT_EXISTS: "account_exists",
  ACCOUNT_DELETED: "account_deleted",
  PASSWORD_CHANGE_REQUIRED: "password_change_required",
} as const;

/**
 * 邮箱后缀不在白名单的固定文案（ADR-0023）：与后端
 * ``accounts.email_domains.EMAIL_DOMAIN_BLOCKED_MESSAGE`` 逐字一致（契约测试钉死），
 * 由 ``NoticeModal`` 弹窗展示。
 */
export const EMAIL_DOMAIN_BLOCKED_MESSAGE =
  "该邮箱后缀暂不可用，请换用其他邮箱。详询社长或服务器管理员";

/**
 * 「本设备已下线」文案（ADR-0028）：与后端 ``accounts.middleware.revoke_copy`` 语义一致。
 * 名额顶替 / 手动下线 / 设备重登 / 安全吊销 各有说法，默认按「他设备登录」。
 */
export function sessionEndedMessage(reason?: string): string {
  switch (reason) {
    case "limit":
      return (
        "你的账号最多同时保持 3 台设备登录。有新设备登录时，最久未使用的那台会被替换下线——" +
        "可在「个人中心 → 登录设备」查看与管理。"
      );
    case "manual":
      return "这台设备已在「个人中心 → 登录设备」中被下线。";
    case "replaced":
      return "这台设备上的旧会话已被同一设备的新登录替换。";
    case "security":
      return "账号安全状态发生变化，请重新登录。";
    default:
      return "您的账号已在另一台设备登录，当前设备已退出登录。";
  }
}

// ---- 纯映射：HTTP 响应 → 类型化结果 ----

/** 把「状态码 + 已解析响应体」映射成类型化 ApiError。reason 串 → kind 的唯一归属。 */
export function classifyHttpResponse(status: number, data: any): ApiError {
  const reason = typeof data?.reason === "string" ? data.reason : null;
  if (reason === REASON.SESSION_SUPERSEDED) {
    const error: ApiError = { kind: "session_superseded", takeover: data?.takeover ?? {} };
    if (typeof data?.revoked_reason === "string" && data.revoked_reason) {
      error.revokedReason = data.revoked_reason;
    }
    return error;
  }
  if (reason === REASON.LOGIN_PROTECTION && typeof data?.retry_after === "number") {
    return { kind: "login_protection", retryAfter: data.retry_after };
  }
  if (reason === REASON.LOGIN_THROTTLED) {
    return {
      kind: "login_throttled",
      retryAfter: typeof data?.retry_after === "number" ? data.retry_after : 0,
    };
  }
  if (reason === REASON.ACCOUNT_DISABLED) {
    return { kind: "account_disabled" };
  }
  if (reason === REASON.EMAIL_NOT_VERIFIED) {
    return { kind: "email_not_verified", email: typeof data?.email === "string" ? data.email : "" };
  }
  if (reason === REASON.EMAIL_DOMAIN_NOT_ALLOWED) {
    return {
      kind: "email_domain_not_allowed",
      domain: typeof data?.domain === "string" ? data.domain : "",
    };
  }
  if (reason === REASON.ACCOUNT_EXISTS) {
    return { kind: "account_exists", field: typeof data?.field === "string" ? data.field : "" };
  }
  if (reason === REASON.ACCOUNT_DELETED) return { kind: "account_deleted" };
  if (reason === REASON.PASSWORD_CHANGE_REQUIRED) return { kind: "password_change_required" };
  if (status === 401) return { kind: "auth" };
  if (status === 403) return { kind: "forbidden" };
  if (status === 404) return { kind: "not_found" };
  return { kind: "http", status };
}

/** 读取一个 HTTP 响应并映射成类型化结果（含成功分支）。响应体非 JSON 归为网络错误。 */
export async function readResponse<T>(res: Response): Promise<ResponseOutcome<T>> {
  if (res.status === 204) return { ok: true, data: null as T };
  let data: any;
  try {
    data = await res.json();
  } catch {
    return { ok: false, error: { kind: "network" }, message: "Failed to fetch" };
  }
  if (res.ok) return { ok: true, data: data as T };
  return {
    ok: false,
    error: classifyHttpResponse(res.status, data),
    message: data?.detail || data?.error || "请求失败",
  };
}

/** 类型化错误 → 中文文案（穷尽 switch；新增 ApiError kind 时编译器在 default 报错）。 */
export function humanizeApiError(err: ApiError): string {
  switch (err.kind) {
    case "session_superseded":
      return sessionEndedMessage(err.revokedReason);
    case "login_protection": {
      const mins = Math.ceil(err.retryAfter / 60);
      return (
        "该账号短时间内登录次数过多，请稍后重试。" +
        (mins > 0 ? `（约 ${mins} 分钟后可重试）` : "")
      );
    }
    case "login_throttled":
      return "登录尝试过于频繁，请稍后再试。";
    case "account_disabled":
      return "账号已被停用，请联系信息组。";
    case "email_not_verified":
      return "请先认证邮箱后再登录。";
    case "email_domain_not_allowed":
      return EMAIL_DOMAIN_BLOCKED_MESSAGE;
    case "account_exists": {
      const label =
        err.field === "username"
          ? "用户名"
          : err.field === "email"
            ? "邮箱"
            : err.field === "real_name_card_no"
              ? "姓名 + 校牌号"
              : "真实姓名";
      return `该${label}已注册，请登录原账户。`;
    }
    case "account_deleted":
      return "该账号已注销，无法登录。如有疑问请联系信息组。";
    case "password_change_required":
      return "请先修改密码后再继续使用。";
    case "network":
      return "网络连接失败，请检查网络后重试。";
    case "auth":
      return "登录已失效，请重新登录。";
    case "forbidden":
      return "您没有权限执行此操作。";
    case "not_found":
      return "请求的资源不存在。";
    case "http":
      return "请求失败，请稍后重试。";
    default: {
      // 穷尽性：新增 ApiError kind 时，TS 在此行报错，强制补分支。
      const _exhaustive: never = err;
      return _exhaustive;
    }
  }
}

// ---- 挤号回调（会话守卫注册；消费类型化结果）----
type SupersedeHandler = (result: SessionSupersededResult) => void;

let supersedeHandler: SupersedeHandler | null = null;

export function setSupersedeHandler(fn: SupersedeHandler | null) {
  supersedeHandler = fn;
}

export function getCSRFToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

import { getDeviceId } from "../utils/deviceId";

// ---- 适配器：独占 fetch / 头 / CSRF / 响应映射 ----
export function createRequest(base: string) {
  return async function request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    const isFormData = options.body instanceof FormData;
    let res: Response;
    try {
      res = await fetch(`${base}${path}`, {
        ...options,
        headers: {
          ...(isFormData ? {} : { "Content-Type": "application/json" }),
          "X-CSRFToken": getCSRFToken(),
          "X-Device-Id": getDeviceId(),
          ...options.headers,
        },
        credentials: "include",
      });
    } catch {
      // 断网/超时：统一成网络错误（#7 故事 11）。message 沿用旧值，过渡期消费方不受影响。
      const err = new Error("Failed to fetch") as Error & { status: number; apiError: ApiError };
      err.status = 0;
      err.apiError = { kind: "network" };
      throw err;
    }
    const result = await readResponse<T>(res);
    if (result.ok) return result.data;
    const { error: apiError, message } = result;
    // 挤号：把类型化「会话被挤下线」结果交给守卫（幂等由 SessionGuard 保证），随后照常抛错。
    if (apiError.kind === "session_superseded") {
      supersedeHandler?.(apiError);
    }
    // 管理员重置密码后的强制改密：任何页面撞到都统一改道（登录页 / 强制页自身不打转）。
    if (apiError.kind === "password_change_required") {
      const target = "#/change-password-required";
      if (window.location.hash !== target) window.location.hash = target;
    }
    const err = new Error(message) as Error & { status: number; apiError: ApiError };
    err.status = res.status;
    err.apiError = apiError;
    throw err;
  };
}
