import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type { PasswordResetRequestItem } from "../types/passwordReset";

const request = createRequest("/auth");

/** 审核台「密码重置」桌的取数与处理（审批权由后端 review_password_reset 收口）。 */
export const passwordResetApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/password-reset-requests/${qs}`) as Promise<Paginated<PasswordResetRequestItem>>;
  },
  approve: (id: number, note = "") =>
    request(`/password-reset-requests/${id}/approve/`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }) as Promise<PasswordResetRequestItem>,
  reject: (id: number, note = "") =>
    request(`/password-reset-requests/${id}/reject/`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }) as Promise<PasswordResetRequestItem>,
};
