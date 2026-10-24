import { createRequest } from "./shared";

const request = createRequest("/auth");

/** 账号安全中心（设计稿 2026-10-24）：总览 / 设备 / 登录记录 / 滚动密钥 / 恢复代码。 */

export interface SecurityOverview {
  password: { enabled: boolean };
  email: { bound: boolean; verified: boolean; address: string };
  questions: { count: number };
  passkeys: { count: number; max: number };
  totp: { count: number; pending: number; max: number };
  recovery: { remaining: number; total: number };
  devices: { count: number; trusted: number; current: number };
  stepup: { available: boolean; email: boolean; questions: boolean; totp: boolean };
}

export interface DeviceRow {
  id: number;
  label: string;
  browser: string;
  platform: string;
  brand: string;
  model: string;
  city: string;
  country: string;
  last_seen: string;
  first_seen: string;
  trusted: boolean;
  is_current: boolean;
}

export interface LoginEventRow {
  id: number;
  created_at: string;
  device_label: string;
  city: string;
  region: string;
  country: string;
  latitude: number | null;
  longitude: number | null;
  method: string;
  status: string;
  second_factor: string;
  is_new_device: boolean;
  ip: string;
}

export interface TotpRow {
  id: number;
  label: string;
  created_at: string;
}

export const securityApi = {
  overview: () => request("/security/overview/") as Promise<SecurityOverview>,

  devices: () => request("/devices/") as Promise<{ results: DeviceRow[] }>,

  revokeDevice: (id: number, headers?: Record<string, string>) =>
    request(`/devices/${id}/`, { method: "DELETE", headers }) as Promise<{ message: string }>,

  loginEvents: (page = 1) =>
    request(`/login-events/?page=${page}`) as Promise<{
      count: number;
      next: string | null;
      results: LoginEventRow[];
    }>,

  totpList: () => request("/totp/") as Promise<{ max: number; results: TotpRow[] }>,

  totpSetup: (label: string) =>
    request("/totp/setup/", { method: "POST", body: JSON.stringify({ label }) }) as Promise<{
      id: number;
      secret: string;
      otpauth: string;
      qr: string;
    }>,

  totpConfirm: (id: number, code: string) =>
    request("/totp/confirm/", { method: "POST", body: JSON.stringify({ id, code }) }) as Promise<{
      message: string;
      recovery_codes: string[] | null;
    }>,

  totpDelete: (id: number, headers?: Record<string, string>) =>
    request(`/totp/${id}/`, { method: "DELETE", headers }) as Promise<{
      message: string;
      remaining: number;
    }>,

  recoveryCodes: (headers?: Record<string, string>) =>
    request("/recovery-codes/", { method: "POST", body: "{}", headers }) as Promise<{
      codes: string[];
      count: number;
    }>,
};
