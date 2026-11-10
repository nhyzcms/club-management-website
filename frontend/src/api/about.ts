import { createRequest } from "./shared";

const request = createRequest("/about");

export interface AboutBlock {
  key: string;
  title: string;
  content: string;
  order: number;
  panorama_url: string;
  document_url: string | null;
  document_name: string;
  updated_at: string;
}

export interface ClubOverview {
  founded: string;
  advisor: string;
  intro: string;
  updated_at: string;
}

export interface AboutPageData {
  blocks: AboutBlock[];
  overview: ClubOverview;
  updated_at: string;
}

export const aboutApi = {
  get: () => request("/") as Promise<AboutPageData>,
  updateBlock: (key: string, data: FormData | Record<string, string>) => {
    const isForm = data instanceof FormData;
    return request(`/blocks/${key}/`, {
      method: "PATCH",
      body: isForm ? data : JSON.stringify(data),
    }) as Promise<AboutBlock>;
  },
  getOverview: () => request("/overview/") as Promise<ClubOverview>,
  updateOverview: (data: { founded: string; advisor: string; intro: string }) =>
    request("/overview/", { method: "PUT", body: JSON.stringify(data) }) as Promise<ClubOverview>,
};
