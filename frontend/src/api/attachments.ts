import { Upload as TusUpload } from "tus-js-client";
import { createRequest, getCSRFToken } from "./shared";
import { getSitePolicy } from "./sitePolicy";
import { Attachment } from "../types/tasks";

const request = createRequest("/attachments");

// 上传必须且只能指定一个父级（task_id 或 feedback_id 或 news_id），用联合类型在编译期固化这条后端约束。
type UploadParams = { file: File } & (
  | { taskId: number; feedbackId?: undefined; newsId?: undefined }
  | { feedbackId: number; taskId?: undefined; newsId?: undefined }
  | { newsId: number; taskId?: undefined; feedbackId?: undefined }
);

// 大文件（超过同步上限的图/视频）走 tus 可续传：POST /uploads/files/ … 完成后由后端 finished 钩子
// 自动挂成统一 Attachment。parent_type/parent_id 经 Upload-Metadata 声明、创建时即校验权限。
type UploadLargeParams = {
  file: File;
  parentType: "task" | "feedback" | "news";
  parentId: number;
  onProgress?: (ratio: number) => void;
};

export const attachmentApi = {
  upload: (params: UploadParams): Promise<Attachment> => {
    const formData = new FormData();
    formData.append("file", params.file);
    if (params.taskId != null) formData.append("task_id", String(params.taskId));
    if (params.feedbackId != null) formData.append("feedback_id", String(params.feedbackId));
    if (params.newsId != null) formData.append("news_id", String(params.newsId));
    return request("/", { method: "POST", body: formData });
  },

  uploadLarge: (params: UploadLargeParams): Promise<void> =>
    new Promise((resolve, reject) => {
      const upload = new TusUpload(params.file, {
        endpoint: "/uploads/files/",
        retryDelays: [0, 1000, 3000, 5000],
        metadata: {
          filename: params.file.name,
          filetype: params.file.type,
          parent_type: params.parentType,
          parent_id: String(params.parentId),
        },
        headers: { "X-CSRFToken": getCSRFToken() },
        onError: (err) => reject(err),
        onProgress: (uploaded, total) => params.onProgress?.(total ? uploaded / total : 0),
        onSuccess: () => resolve(),
      });
      upload.start();
    }),

  // 按大小选路：≤ sync_upload_max_bytes 走同步（返回新建的 Attachment）、超过走 tus 可续传
  // （完成时由后端 finished 钩子建附件、返回 void，调用方需重新拉取父级以拿到该附件）。
  uploadRouted: (params: {
    parentType: "task" | "feedback" | "news";
    parentId: number;
    file: File;
    onProgress?: (ratio: number) => void;
  }): Promise<Attachment | void> => {
    if (params.file.size <= getSitePolicy().sync_upload_max_bytes) {
      return attachmentApi.upload(
        params.parentType === "task"
          ? { taskId: params.parentId, file: params.file }
          : params.parentType === "feedback"
            ? { feedbackId: params.parentId, file: params.file }
            : { newsId: params.parentId, file: params.file },
      );
    }
    return attachmentApi.uploadLarge({
      parentType: params.parentType,
      parentId: params.parentId,
      file: params.file,
      onProgress: params.onProgress,
    });
  },

  delete: (attachmentId: number): Promise<null> =>
    request(`/${attachmentId}/`, { method: "DELETE" }),
};
