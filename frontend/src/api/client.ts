import { createRequest } from "./shared";

const request = createRequest("/auth");

export const api = {
  login: (username: string, password: string) =>
    request("/login/", { method: "POST", body: JSON.stringify({ username, password }) }),

  loginWithEmail: (email: string, password: string) =>
    request("/login/", { method: "POST", body: JSON.stringify({ email, password }) }),

  logout: () =>
    request("/logout/", { method: "POST" }),

  me: () =>
    request("/me/"),

  verificationStatus: () =>
    request("/verification/"),

  verificationEmailBind: (email: string, stepup?: Record<string, string>) =>
    request("/verification/email/bind/", { method: "POST", body: JSON.stringify({ email }), headers: stepup }),

  verificationManualSubmit: (data: FormData) =>
    request("/verification/manual/submit/", { method: "POST", body: data }),

  // 认证码通道（ADR-0020）：只兑换、不生成（码由管理员在 Django 后台生成）。
  verificationAuthcodeRedeem: (code: string) =>
    request("/verification/authcode/redeem/", { method: "POST", body: JSON.stringify({ code }) }),

  listSessions: () =>
    request("/sessions/"),

  getCsrf: () =>
    request("/csrf/"),

  register: (data: FormData) =>
    request("/register/", { method: "POST", body: data }),

  // 社员身份（Part A / ADR-0025）：状态 / 认领 / 公开扫码校验。
  memberIdentity: () => request("/member/"),

  memberClaim: (identityId: number, phoneLast4: string) =>
    request("/member/claim/", {
      method: "POST",
      body: JSON.stringify({ identity_id: identityId, phone_last4: phoneLast4 }),
    }),

  memberCheck: (code: string, sig: string) =>
    request(`/member/check/?c=${encodeURIComponent(code)}&s=${encodeURIComponent(sig)}`),

  verifyEmail: (uid: string, token: string) =>
    request(`/verify-email/?uid=${encodeURIComponent(uid)}&token=${encodeURIComponent(token)}`),

  resendVerification: (email: string, turnstileToken = "") =>
    request("/resend-verification/", {
      method: "POST",
      body: JSON.stringify({
        email,
        ...(turnstileToken ? { turnstile_token: turnstileToken } : {}),
      }),
    }),

  passwordReset: (email: string, turnstileToken = "") =>
    request("/password-reset/", {
      method: "POST",
      body: JSON.stringify({
        email,
        ...(turnstileToken ? { turnstile_token: turnstileToken } : {}),
      }),
    }),

  passwordResetConfirm: (uid: string, token: string, new_password: string) =>
    request("/password-reset/confirm/", { method: "POST", body: JSON.stringify({ uid, token, new_password }) }),

  getProfile: () =>
    request("/profile/"),

  updateProfile: (data: FormData) =>
    request("/profile/update/", { method: "POST", body: data }),

  changePassword: (old_password: string, new_password: string, stepup?: Record<string, string>) =>
    request("/profile/change-password/", {
      method: "POST",
      body: JSON.stringify({ old_password, new_password }),
      headers: stepup,
    }),

  // 账号注销（ADR-0025）：不可逆；须当前密码 + 逐字确认，敏感操作另需安全验证 grant。
  deleteAccount: (password: string, stepup?: Record<string, string>) =>
    request("/account/delete/", {
      method: "POST",
      body: JSON.stringify({ password, confirm: "注销账号" }),
      headers: stepup,
    }) as Promise<{ message: string }>,

  // 账号有效期（ADR-0041）：状态 / 到期时间 / 剩余天数 / 一次性提示键。
  // “已读”写回服务端（Profile.validity_notice_ack），跨设备一致。
  accountValidity: () =>
    request("/validity/"),
  accountValidityAck: (key: string) =>
    request("/validity/ack/", { method: "POST", body: JSON.stringify({ key }) }),

  listUsers: () =>
    request("/users/"),
  // 用户搜索（任务表单指派/协作者）：分页信封 + ?search=（用户名/昵称模糊）
  searchUsers: (search: string) =>
    request(`/users/${search ? `?search=${encodeURIComponent(search)}` : ""}`) as Promise<{
      count: number;
      next: string | null;
      previous: string | null;
      results: { id: number; username: string; nickname: string; avatar: string | null }[];
    }>,

  getUserProfile: (id: number) =>
    request(`/users/${id}/profile/`),

  getUserContent: (id: number, type: "news" | "feedback" | "tasks" | "activities" | "tutorials", page = 1) =>
    request(`/users/${id}/content/?type=${type}&page=${page}`),

  inbox: () => request("/inbox/"),
};
