import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type { FeedbackDetail, FeedbackFormData, FeedbackListItem } from "../types/feedback";

const request = createRequest("/reviews");

export const feedbackApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/feedbacks/${qs}`) as Promise<Paginated<FeedbackListItem>>;
  },
  get: (id: number) => request(`/feedbacks/${id}/`) as Promise<FeedbackDetail>,
  submit: (data: FeedbackFormData) =>
    request("/feedbacks/submit/", { method: "POST", body: JSON.stringify(data) }) as Promise<FeedbackDetail>,
  close: (id: number, note: string) =>
    request(`/feedbacks/${id}/close/`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }) as Promise<FeedbackDetail>,
};
