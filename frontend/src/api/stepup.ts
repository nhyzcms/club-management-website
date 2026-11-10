import { createRequest } from "./shared";

const request = createRequest("/auth");

/**
 * 安全验证（Step-up，ADR-0026；2026-10-25 起改为「因子注册表」）：
 * - 可用验证方式由后端 `GET /auth/stepup/?scope=` 下发，前端不再写死；
 * - 通过后签发 grant（10 分钟、同 scope 复用），存 sessionStorage，随受保护调用带
 *   `X-StepUp-Grant` 头；受保护端点缺令牌会回 403 `step_up_required`。
 */

export const STEPUP_SCOPE_LABELS: Record<string, string> = {
  change_password: "修改密码",
  manage_questions: "管理安全问题",
  change_email: "换绑邮箱",
  delete_account: "注销账号",
  manage_devices: "管理登录设备",
  manage_totp: "管理动态口令",
};

/** 一个验证因子（后端注册表下发）。新增方式时这里不需要改。 */
export interface StepupFactor {
  key: string;
  label: string;
  hint: string;
  sends_code: boolean;
}

export interface StepupStatus {
  scopes: Record<string, string>;
  factors: StepupFactor[];
  email: { available: boolean; address: string; cooldown_remaining: number };
  questions: { configured: boolean; count: number };
  grant_ttl: number;
}

export interface StepupBankItem {
  key: string;
  text: string;
}

export interface StepupQuestion {
  id: number;
  key: string;
  text: string;
}

export interface StepupEvent {
  scope: string;
  scope_label: string;
  method: string;
  result: string;
  ip: string | null;
  created_at: string;
}

const GRANT_PREFIX = "stepup_grant:";

export function storeGrant(scope: string, grant: string): void {
  try {
    sessionStorage.setItem(GRANT_PREFIX + scope, grant);
  } catch {
    /* 隐私模式等场景：内存不存，行为降级为「每次都要验证」 */
  }
}

export function grantFor(scope: string): string {
  try {
    return sessionStorage.getItem(GRANT_PREFIX + scope) || "";
  } catch {
    return "";
  }
}

export function clearGrant(scope: string): void {
  try {
    sessionStorage.removeItem(GRANT_PREFIX + scope);
  } catch {
    /* noop */
  }
}

/** 受保护调用附带的请求头（无 grant 时为空对象）。 */
export function stepupHeaders(scope: string): Record<string, string> {
  const grant = grantFor(scope);
  return grant ? { "X-StepUp-Grant": grant } : {};
}

export const stepupApi = {
  status: (scope?: string) =>
    request(scope ? `/stepup/?scope=${encodeURIComponent(scope)}` : "/stepup/") as Promise<StepupStatus>,

  emailSend: () =>
    request("/stepup/email/send/", { method: "POST" }) as Promise<{ message: string }>,

  verify: (data: {
    method: string;
    scope: string;
    code?: string;
    question_id?: number;
    answer?: string;
  }) =>
    request("/stepup/verify/", { method: "POST", body: JSON.stringify(data) }) as Promise<{
      message: string;
      grant: string;
      expires_in: number;
    }>,

  questions: () =>
    request("/stepup/questions/") as Promise<{ bank: StepupBankItem[]; mine: StepupQuestion[] }>,

  questionsSet: (items: { key: string; answer: string }[], password?: string) =>
    request("/stepup/questions/", {
      method: "POST",
      body: JSON.stringify({ items, ...(password ? { password } : {}) }),
    }) as Promise<{ message: string; count: number }>,

  events: () => request("/stepup/events/") as Promise<{ results: StepupEvent[] }>,
};

/**
 * 受保护调用遇 403 `step_up_required` 时统一跳转：
 * `/#/verify?action=<scope>&next=<当前地址>`；验证完成后 StepUpPage 回跳。
 */
export function redirectToStepUp(scope: string, next?: string): void {
  const target = next ?? `${window.location.hash.replace(/^#/, "") || "/"}`;
  window.location.hash = `#/verify?action=${encodeURIComponent(scope)}&next=${encodeURIComponent(target)}`;
}
