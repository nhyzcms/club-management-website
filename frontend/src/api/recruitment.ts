import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";

const request = createRequest("/recruitment");

export interface RecruitmentLanding {
  notice: { content: string; updated_at: string };
  schema: Record<string, unknown>;
  already_responded: boolean;
  responded_count: number;
  max_submissions: number;
}

export const recruitmentApi = {
  landing: () => request("/") as Promise<RecruitmentLanding>,
  updateNotice: (content: string) =>
    request("/notice/", { method: "PUT", body: JSON.stringify({ content }) }) as Promise<{ content: string; updated_at: string }>,
  getSchema: () => request("/schema/") as Promise<{ schema: Record<string, unknown>; updated_at: string }>,
  updateSchema: (schema: Record<string, unknown>) =>
    request("/schema/", { method: "PUT", body: JSON.stringify({ schema }) }),
  submit: (answers: Record<string, unknown>, noticeAcknowledged: boolean) =>
    request("/responses/", {
      method: "POST",
      body: JSON.stringify({ answers, notice_acknowledged: noticeAcknowledged }),
    }) as Promise<{ ok: boolean; id: number; message: string }>,
  responses: () => request("/responses/") as Promise<Paginated<{ id: number; answers: Record<string, unknown>; submitted_at: string }>>,
};
