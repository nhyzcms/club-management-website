import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";

const request = createRequest("/tutorials");

export interface TutorialUser {
  id: number;
  username: string;
  nickname: string;
  avatar: string | null;
}

export interface TutorialItem {
  id: number;
  title: string;
  description: string;
  file_type: "video" | "document";
  file_name: string;
  file_size: number;
  file_url?: string;
  cover_url: string | null;
  uploader: TutorialUser;
  views: number;
  favorite_count: number;
  favorited: boolean;
  review_status: "pending" | "approved" | "rejected" | "removed" | null;
  created_at: string;
  updated_at?: string;
  review_comment?: string;
}

export const tutorialApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/tutorials/${qs}`) as Promise<Paginated<TutorialItem>>;
  },
  get: (id: number) => request(`/tutorials/${id}/`) as Promise<TutorialItem>,
  create: (data: FormData) =>
    request("/tutorials/", { method: "POST", body: data }) as Promise<TutorialItem>,
  mine: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/tutorials/mine/${qs}`) as Promise<Paginated<TutorialItem>>;
  },
  favorite: (id: number) =>
    request(`/tutorials/${id}/favorite/`, { method: "POST", body: "{}" }) as Promise<TutorialItem>,
};
