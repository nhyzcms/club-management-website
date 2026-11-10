import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type { IdentityReviewItem } from "../types/identityReviews";

const request = createRequest("/auth");

export const identityReviewsApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/identity-reviews/${qs}`) as Promise<Paginated<IdentityReviewItem>>;
  },
  approve: (id: number) =>
    request(`/identity-reviews/${id}/approve/`, { method: "POST", body: "{}" }) as Promise<IdentityReviewItem>,
  reject: (id: number) =>
    request(`/identity-reviews/${id}/reject/`, { method: "POST", body: "{}" }) as Promise<IdentityReviewItem>,
  disable: (id: number) =>
    request(`/identity-reviews/${id}/disable/`, { method: "POST", body: "{}" }) as Promise<IdentityReviewItem>,
};
