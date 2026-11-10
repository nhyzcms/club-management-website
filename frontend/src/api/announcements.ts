import type { Announcement } from "../types/announcements";
import { createRequest } from "./shared";

const request = createRequest("/announcements");

export const announcementsApi = {
  /** 当前用户还没读过的在线公告（匿名只看「全站」受众）。 */
  active: () =>
    request("/active/") as Promise<{ count: number; results: Announcement[] }>,

  /** 详情（站内通知点击回看；同样按受众鉴权，受众外 404）。 */
  get: (id: number) => request(`/${id}/`) as Promise<Announcement>,

  /** 记已读（幂等）。匿名调用会 401，调用方自行忽略。 */
  markRead: (id: number) =>
    request(`/${id}/read/`, { method: "POST" }) as Promise<{
      read_at: string;
      already_read: boolean;
    }>,
};
