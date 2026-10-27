/**
 * 问卷 Schema 的纯函数小工具（不依赖 SurveyJS，可在 node 环境直接单测）。
 *
 * 用途：活动「发起 / 编辑」表单里的问卷设计摘要——统计题目数、判断是否空表。
 * 真正的拖拽编辑由 `components/SurveyDesignerModal.tsx`（SurveyJS Creator）完成，
 * 表单只持有 Schema 对象，提交时随活动一起发给后端（`POST/PATCH /activities/activities/`）。
 */

export type SurveySchema = Record<string, unknown>;

/** 一页空问卷：与后端 `activities.models.default_survey_schema()` 同形。 */
export const EMPTY_SURVEY_SCHEMA: SurveySchema = {
  title: "",
  pages: [{ name: "page1", elements: [] }],
};

/**
 * 递归统计题目数。
 *
 * - `panel` 只是容器，本身不算题，继续下钻它的 `elements`；
 * - **选项内子题**（`choices[i].elements`，选中该选项时就地展开）也是题，一起数；
 * - 兼容 SurveyJS 把页面写成 `elements` 的常见形状，非数组一律忽略。
 */
export function countSurveyQuestions(schema: unknown): number {
  if (!schema || typeof schema !== "object") return 0;
  const pages = (schema as SurveySchema).pages;
  if (!Array.isArray(pages)) return 0;

  let count = 0;
  const seen = new Set<string>();
  const walk = (elements: unknown, depth = 0) => {
    if (!Array.isArray(elements) || depth > 8) return;
    for (const raw of elements) {
      if (!raw || typeof raw !== "object") continue;
      const el = raw as SurveySchema;
      if (el.type === "panel") {
        walk(el.elements, depth + 1);
        continue;
      }
      const name = typeof el.name === "string" ? el.name : "";
      if (name) {
        if (seen.has(name)) continue;
        seen.add(name);
      }
      count += 1;
      if (Array.isArray(el.choices)) {
        for (const choice of el.choices) {
          if (choice && typeof choice === "object") {
            walk((choice as SurveySchema).elements, depth + 1);
          }
        }
      }
    }
  };

  for (const page of pages) {
    if (page && typeof page === "object") walk((page as SurveySchema).elements);
  }
  return count;
}

/** 设计摘要文案：「N 道题目」/「尚未添加题目」。 */
export function summarizeSurveySchema(schema: unknown): string {
  const n = countSurveyQuestions(schema);
  return n > 0 ? `${n} 道题目` : "尚未添加题目";
}
