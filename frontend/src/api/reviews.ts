import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type { ReviewItem } from "../types/reviews";

const request = createRequest("/reviews");

export const reviewsApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/reviews/${qs}`) as Promise<Paginated<ReviewItem>>;
  },
  approve: (id: number) =>
    request(`/reviews/${id}/approve/`, { method: "POST", body: "{}" }) as Promise<ReviewItem>,
  reject: (id: number, comment: string) =>
    request(`/reviews/${id}/reject/`, {
      method: "POST",
      body: JSON.stringify({ comment }),
    }) as Promise<ReviewItem>,
  remove: (id: number) =>
    request(`/reviews/${id}/remove/`, { method: "POST", body: "{}" }) as Promise<ReviewItem>,
};
