import { describe, expect, it } from "vitest";
import {
  EMPTY_SURVEY_SCHEMA,
  countSurveyQuestions,
  summarizeSurveySchema,
} from "../surveySchema";

describe("countSurveyQuestions", () => {
  it("空表 / 非法输入都算 0 题", () => {
    expect(countSurveyQuestions(EMPTY_SURVEY_SCHEMA)).toBe(0);
    expect(countSurveyQuestions(null)).toBe(0);
    expect(countSurveyQuestions(undefined)).toBe(0);
    expect(countSurveyQuestions("x")).toBe(0);
    expect(countSurveyQuestions({})).toBe(0);
    expect(countSurveyQuestions({ pages: "nope" })).toBe(0);
  });

  it("跨页累加，忽略非法元素", () => {
    const schema = {
      pages: [
        { name: "p1", elements: [{ type: "text", name: "q1" }, null, "junk"] },
        { name: "p2", elements: [{ type: "radiogroup", name: "q2" }] },
      ],
    };
    expect(countSurveyQuestions(schema)).toBe(2);
  });

  it("panel 是容器不计入，但下钻其子题", () => {
    const schema = {
      pages: [
        {
          name: "p1",
          elements: [
            { type: "panel", name: "p", elements: [{ type: "text", name: "a" }, { type: "text", name: "b" }] },
            { type: "dropdown", name: "c" },
          ],
        },
      ],
    };
    expect(countSurveyQuestions(schema)).toBe(3);
  });

  it("选项内子题也计入（含多级嵌套），同名题目只数一次", () => {
    const schema = {
      pages: [
        {
          name: "p1",
          elements: [
            {
              type: "checkbox",
              name: "devices",
              choices: [
                { value: "item1", text: "数码相机", elements: [{ type: "text", name: "model" }] },
                {
                  value: "item2",
                  text: "相机配件",
                  elements: [
                    {
                      type: "checkbox",
                      name: "parts",
                      choices: [{ value: "item1", text: "镜头", elements: [{ type: "text", name: "lens" }] }],
                    },
                  ],
                },
              ],
            },
            { type: "text", name: "note" },
            { type: "text", name: "note" },
          ],
        },
      ],
    };
    // devices + model + parts + lens + note（重复的 note 只算一次）
    expect(countSurveyQuestions(schema)).toBe(5);
  });
});

describe("summarizeSurveySchema", () => {
  it("有题给数量，没题给提示", () => {
    expect(summarizeSurveySchema(EMPTY_SURVEY_SCHEMA)).toBe("尚未添加题目");
    expect(
      summarizeSurveySchema({ pages: [{ name: "p1", elements: [{ type: "text", name: "q" }] }] }),
    ).toBe("1 道题目");
  });
});
