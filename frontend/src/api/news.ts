import { createRequest } from "./shared";
import type { NewsDetail, NewsListItem, NewsTag } from "../types/news";
import type { FeedResponse } from "../types/feed";

const request = createRequest("/news");

export interface NewsListResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: NewsListItem[];
}

/** 服务端草稿区：已发布新闻的待发布修改（编辑页自动保存）。 */
export interface NewsDraft {
  title: string;
  summary: string;
  content: string;
  saved_at: string;
}

/** 草稿保存回执：is_draft=false 表示写入的是未发布稿件正文（稿件本体即草稿）。 */
export interface NewsDraftSaveResult {
  saved_at: string;
  is_draft: boolean;
}

// list 为分页响应；featured/hot/tags 为自定义 action，直接返回对象/数组（不分页）
export const newsApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/news/${qs}`) as Promise<NewsListResponse>;
  },
  get: (id: number) => request(`/news/${id}/`) as Promise<NewsDetail>,
  mine: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/news/mine/${qs}`) as Promise<NewsListResponse>;
  },
  create: (data: FormData) => request("/news/", { method: "POST", body: data }) as Promise<NewsDetail>,
  update: (id: number, data: FormData) => request(`/news/${id}/`, { method: "PATCH", body: data }) as Promise<NewsDetail>,
  remove: (id: number) => request(`/news/${id}/`, { method: "DELETE" }),
  // —— 服务端草稿区（编辑页自动保存；读 / 存 / 弃均须 news.manage_news）——
  getDraft: (id: number) => request(`/news/${id}/draft/`) as Promise<{ draft: NewsDraft | null }>,
  saveDraft: (id: number, data: { title?: string; summary?: string; content?: string }) =>
    request(`/news/${id}/draft/`, { method: "POST", body: JSON.stringify(data) }) as Promise<NewsDraftSaveResult>,
  discardDraft: (id: number) => request(`/news/${id}/draft/`, { method: "DELETE" }) as Promise<{ draft: null }>,
  // 正文内嵌图片上传（信息组）：返回 {url}，供编辑器「插入图片」与 Word 导入内嵌图片使用
  uploadImage: (file: File) => {
    const fd = new FormData();
    fd.append("image", file);
    return request("/news/upload_image/", { method: "POST", body: fd }) as Promise<{ url: string }>;
  },
  // 封面预上传（信息组）：「选完即传」——返回 {url}，保存时以 cover_image_ref 引用挂载
  uploadCover: (file: File) => {
    const fd = new FormData();
    fd.append("image", file);
    return request("/news/upload_cover/", { method: "POST", body: fd }) as Promise<{ url: string }>;
  },
  featured: () => request("/news/featured/") as Promise<NewsListItem | null>,
  hot: () => request("/news/hot/") as Promise<NewsListItem[]>,
  tags: () => request("/news/tags/") as Promise<NewsTag[]>,
  // 社团概览：成员=已分配社员编号数（名册行数，与是否注册账号无关），作品=已发布新闻数（匿名可读）
  overview: () => request("/news/overview/") as Promise<{ members: number; works: number }>,
  // 首页「社团动态」聚合：{featured, items}（匿名可读；任务仅登录下发）
  feed: (limit = 6) => request(`/news/feed/?limit=${limit}`) as Promise<FeedResponse>,
};
