import { Model } from "survey-core";
import { activityApi } from "../api/activities";
import { SURVEY_LOCALE } from "./surveyLocale";

/** Shared SurveyJS fill model: responsive width + a complete handler. Used by join and 调研. */
export function createSurveyModel(
  schema: Record<string, unknown>,
  onComplete: (answers: Record<string, unknown>) => void | Promise<void>,
): Model {
  const m = new Model(schema);
  m.locale = SURVEY_LOCALE;
  m.widthMode = "responsive";
  m.onComplete.add((sender) => {
    void onComplete(sender.data as Record<string, unknown>);
  });
  // 文件题上传兜底：SurveyJS 默认把文件传到 surveyjs.io 海外服务（不可用），
  // 这里改为上传到本站（/activities/survey_upload/），把返回 URL 存进答案。
  m.onUploadFiles.add((_sender, options) => {
    void (async () => {
      const uploaded: { file: File; content: string }[] = [];
      const errors: string[] = [];
      for (const file of options.files) {
        try {
          const { url } = await activityApi.surveyUpload(file);
          uploaded.push({ file, content: url });
        } catch (e: any) {
          errors.push(e?.message || `「${file.name}」上传失败`);
        }
      }
      options.callback(uploaded, errors.length ? errors : undefined);
    })();
  });
  return m;
}
