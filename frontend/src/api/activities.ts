import { createRequest } from "./shared";
import type {
  ActivityDetail,
  ActivityListItem,
  ActivityFormData,
  SurveyResponsesPayload,
} from "../types/activities";

const request = createRequest("/activities");

export interface ActivityListResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: ActivityListItem[];
}

export const activityApi = {
  list: (params?: Record<string, string>): Promise<ActivityListResponse> => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/activities/${qs}`);
  },
  get: (id: number): Promise<ActivityDetail> => request(`/activities/${id}/`),
  mine: (params?: Record<string, string>): Promise<ActivityListResponse> => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request(`/activities/mine/${qs}`);
  },
  create: (data: ActivityFormData): Promise<ActivityDetail> =>
    request("/activities/", { method: "POST", body: JSON.stringify(data) }),
  update: (id: number, data: Record<string, unknown>): Promise<ActivityDetail> =>
    request(`/activities/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
  remove: (id: number) => request(`/activities/${id}/`, { method: "DELETE" }),

  // 众议投票（option_ids：选 1..K 项；展示的 option_ids 即展品的 vote_option_id）
  vote: (id: number, optionIds: number[]): Promise<ActivityDetail> =>
    request(`/activities/${id}/vote/`, {
      method: "POST",
      body: JSON.stringify({ option_ids: optionIds }),
    }),

  // 调研作答（公开受众任何人；仅成员须登录；已登录一人一次；访客按设备一次）
  respond: (id: number, answers: Record<string, unknown>): Promise<ActivityDetail> =>
    request(`/activities/${id}/respond/`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),

  // 问卷作答查看（发起人/管理 → 全部；其他登录用户 → 自己的）
  // query：对作答内容做模糊检索（后端 ?q=，只匹配用户填写的值）
  responses: (id: number, query?: string): Promise<SurveyResponsesPayload> => {
    const qs = query ? "?" + new URLSearchParams({ q: query }).toString() : "";
    return request(`/activities/${id}/responses/${qs}`);
  },

  // 众议 / 展示 / 征集 / 调研：提前关闭（众议/展示/调研立即结算；征集结束收件进入复审或归档）
  close: (id: number): Promise<ActivityDetail> =>
    request(`/activities/${id}/close/`, { method: "POST" }),

  // 征集投稿（multipart：一束文件 = 一个作品，提交即锁定）
  submit: (id: number, files: File[]): Promise<ActivityDetail> => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return request(`/activities/${id}/submit/`, { method: "POST", body: fd });
  },

  // 征集复审（录用 / 退稿）
  review: (
    id: number,
    submissionId: number,
    decision: "accepted" | "rejected",
    comment = ""
  ): Promise<ActivityDetail> =>
    request(`/activities/${id}/review_submission/`, {
      method: "POST",
      body: JSON.stringify({
        submission_id: submissionId,
        decision,
        comment,
      }),
    }),

  // 展示：点赞 / 点踩（三态切换：再点当前态=取消）
  rate: (id: number, exhibitId: number, choice: "like" | "dislike"): Promise<ActivityDetail> =>
    request(`/activities/${id}/rate/`, {
      method: "POST",
      body: JSON.stringify({ exhibit_id: exhibitId, choice }),
    }),

  // 展示布展(待开始期):手动加展品(multipart: title + files)
  addExhibit: (id: number, title: string, files: File[]): Promise<ActivityDetail> => {
    const fd = new FormData();
    if (title) fd.append("title", title);
    for (const f of files) fd.append("files", f);
    return request(`/activities/${id}/add_exhibit/`, { method: "POST", body: fd });
  },

  // 改展品(title 给了就改 + 同步选项;files 给了就整体覆盖)
  updateExhibit: (id: number, exhibitId: number, title: string | null, files: File[] | null): Promise<ActivityDetail> => {
    const fd = new FormData();
    fd.append("exhibit_id", String(exhibitId));
    if (title != null) fd.append("title", title);
    if (files) for (const f of files) fd.append("files", f);
    return request(`/activities/${id}/update_exhibit/`, { method: "POST", body: fd });
  },

  // 删展品(连带删附件 + 绑定选项)
  deleteExhibit: (id: number, exhibitId: number): Promise<ActivityDetail> =>
    request(`/activities/${id}/delete_exhibit/`, {
      method: "POST",
      body: JSON.stringify({ exhibit_id: exhibitId }),
    }),

  // 从征集导入(勾选任意作品,复制独立副本)
  importFromCollection: (id: number, collectionId: number, submissionIds: number[]): Promise<ActivityDetail> =>
    request(`/activities/${id}/import_from_collection/`, {
      method: "POST",
      body: JSON.stringify({ collection_id: collectionId, submission_ids: submissionIds }),
    }),

  // 正文内嵌图片上传（已认证成员）：返回 {url}
  uploadImage: (file: File): Promise<{ url: string }> => {
    const fd = new FormData();
    fd.append("image", file);
    return request("/activities/upload_image/", { method: "POST", body: fd });
  },

  // 问卷文件题上传（填答者，含游客）：返回 {url}
  surveyUpload: (file: File): Promise<{ url: string }> => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/activities/survey_upload/", { method: "POST", body: fd });
  },
};
