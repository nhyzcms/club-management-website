import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type { ReportCase, ReportTargetType } from "../types/reports";

const request = createRequest("/reviews");

export const reportsApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/reports/${qs}`) as Promise<Paginated<ReportCase>>;
  },
  get: (id: number) => request(`/reports/${id}/`) as Promise<ReportCase>,
  file: (data: { target_type: ReportTargetType; target_id: number; reason: string }) =>
    request("/reports/", { method: "POST", body: JSON.stringify(data) }) as Promise<{
      id: number;
      status: string;
      target_type: ReportTargetType;
      target_id: number;
    }>,
  dismiss: (id: number, comment: string) =>
    request(`/reports/${id}/dismiss/`, {
      method: "POST",
      body: JSON.stringify({ comment }),
    }) as Promise<ReportCase>,
  uphold: (id: number, body?: { comment?: string; ends_at?: string | null }) =>
    request(`/reports/${id}/uphold/`, {
      method: "POST",
      body: JSON.stringify(body || {}),
    }) as Promise<ReportCase>,
};
