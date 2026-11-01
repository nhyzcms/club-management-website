"""问卷导出单元测试：统计聚合 + CSV / PDF 生成（activities/survey_export.py）。

JSON 导出已移除；多份问卷支持聚合为单个文件。
"""
from django.contrib.auth.models import User
from django.test import TestCase

from . import survey_export
from .models import Questionnaire, QuestionnaireResponse


def _schema():
    return {
        "title": "测试问卷",
        "pages": [{
            "name": "p1",
            "elements": [
                {"type": "radiogroup", "name": "grade", "title": "年级", "choices": ["高一", "高二"]},
                {"type": "checkbox", "name": "skills", "title": "方向", "choices": ["摄影", "剪辑"]},
                {"type": "rating", "name": "score", "title": "评分"},
                {"type": "text", "name": "note", "title": "备注"},
                {"type": "file", "name": "attach", "title": "作品"},
            ],
        }],
    }


class SurveyExportTest(TestCase):
    def setUp(self):
        self.q = Questionnaire.objects.create(kind=Questionnaire.KIND_SURVEY, schema=_schema())
        self.u = User.objects.create_user(username="stu", password="x")
        QuestionnaireResponse.objects.create(
            questionnaire=self.q, user=self.u,
            answers={
                "grade": "高一", "skills": ["摄影", "剪辑"], "score": 4, "note": "你好",
                "attach": [{"name": "a.png", "content": "https://x/a.png"}],
            },
        )
        QuestionnaireResponse.objects.create(
            questionnaire=self.q,
            answers={"grade": "高二", "skills": ["摄影"], "score": 5},
        )

    def _make_second(self):
        q2 = Questionnaire.objects.create(
            kind=Questionnaire.KIND_SURVEY,
            schema={**_schema(), "title": "第二份问卷"},
        )
        QuestionnaireResponse.objects.create(questionnaire=q2, answers={"grade": "高一", "note": "ok"})
        return q2

    # ---- 聚合 ----

    def test_stats_aggregates(self):
        stats = survey_export.compute_stats(_schema(), [r.answers for r in self.q.responses.all()])
        by_name = {s["name"]: s for s in stats}
        self.assertEqual(by_name["grade"]["counts"]["高一"], 1)
        self.assertEqual(by_name["grade"]["counts"]["高二"], 1)
        self.assertEqual(by_name["skills"]["counts"]["摄影"], 2)
        self.assertEqual(by_name["skills"]["counts"]["剪辑"], 1)
        self.assertEqual(by_name["score"]["average"], 4.5)
        self.assertEqual(by_name["note"]["answers"], ["你好"])

    # ---- 统计导出 ----

    def test_stats_csv_single(self):
        data, content_type, filename = survey_export.export_stats([self.q], "csv")
        text = data.decode("utf-8-sig")
        self.assertIn("年级", text)
        self.assertIn("高一", text)
        self.assertEqual(filename, f"survey-stats-{self.q.pk}.csv")
        self.assertIn("text/csv", content_type)

    def test_stats_json_removed(self):
        with self.assertRaises(ValueError):
            survey_export.export_stats([self.q], "json")

    def test_stats_pdf_single(self):
        data, content_type, filename = survey_export.export_stats([self.q], "pdf")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(content_type, "application/pdf")
        self.assertEqual(filename, f"survey-stats-{self.q.pk}.pdf")

    def test_stats_csv_multi(self):
        q2 = self._make_second()
        data, content_type, filename = survey_export.export_stats([self.q, q2], "csv")
        text = data.decode("utf-8-sig")
        self.assertTrue(text.splitlines()[0].startswith("问卷"))  # 多份时首列为「问卷」
        self.assertIn("第二份问卷", text)
        self.assertIn("batch-2", filename)

    def test_stats_pdf_multi(self):
        q2 = self._make_second()
        data, content_type, filename = survey_export.export_stats([self.q, q2], "pdf")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn("batch-2", filename)

    # ---- 作答导出 ----

    def test_responses_csv_single(self):
        data, content_type, filename = survey_export.export_responses([self.q], "csv")
        text = data.decode("utf-8-sig")
        self.assertIn("stu", text)
        self.assertIn("高一", text)
        self.assertIn("访客", text)  # 无 user 无 device 的匿名行
        self.assertEqual(filename, f"survey-responses-{self.q.pk}.csv")

    def test_responses_json_removed(self):
        with self.assertRaises(ValueError):
            survey_export.export_responses([self.q], "json")

    def test_responses_pdf_single(self):
        data, content_type, filename = survey_export.export_responses([self.q], "pdf")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(content_type, "application/pdf")

    def test_responses_csv_multi(self):
        q2 = self._make_second()
        data, content_type, filename = survey_export.export_responses([self.q, q2], "csv")
        text = data.decode("utf-8-sig")
        self.assertIn("问卷：测试问卷", text)
        self.assertIn("问卷：第二份问卷", text)
        self.assertIn("batch-2", filename)

    def test_responses_pdf_multi(self):
        q2 = self._make_second()
        data, content_type, filename = survey_export.export_responses([self.q, q2], "pdf")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn("batch-2", filename)


def _schema_item_values():
    """SurveyJS 默认 value 形态：{value: item1, text: 展示文本}。"""
    return {
        "title": "值文本问卷",
        "pages": [{"name": "p1", "elements": [
            {"type": "radiogroup", "name": "grade", "title": "年级",
             "choices": [{"value": "item1", "text": "高一"}, {"value": "item2", "text": "高二"}]},
            {"type": "checkbox", "name": "skills", "title": "方向",
             "choices": [{"value": "item1", "text": "摄影"}, {"value": "item2", "text": "剪辑"}]},
        ]}],
    }


class SurveyChoiceLabelsTest(TestCase):
    """回归：SurveyJS 默认 value（item1/item2…）在导出时须还原为展示文本。"""

    def setUp(self):
        self.q = Questionnaire.objects.create(kind=Questionnaire.KIND_SURVEY, schema=_schema_item_values())
        QuestionnaireResponse.objects.create(
            questionnaire=self.q,
            answers={"grade": "item2", "skills": ["item1", "item2"]},
        )

    def test_extract_choice_labels(self):
        qs = {q["name"]: q for q in survey_export.extract_questions(self.q.schema)}
        self.assertEqual(qs["grade"]["choices"], ["item1", "item2"])
        self.assertEqual(qs["grade"]["choice_labels"], {"item1": "高一", "item2": "高二"})

    def test_stats_labels_sorted_counts(self):
        stats = survey_export.compute_stats(self.q.schema, [r.answers for r in self.q.responses.all()])
        by_name = {s["name"]: s for s in stats}
        items = dict(survey_export._sorted_counts(by_name["grade"]))
        self.assertEqual(items["高一"], 0)  # 未选中选项保留零计数（分布图显示全部选项）
        self.assertEqual(items["高二"], 1)

    def test_stats_csv_shows_text_not_value(self):
        data, _, _ = survey_export.export_stats([self.q], "csv")
        text = data.decode("utf-8-sig")
        self.assertIn("高一", text)
        self.assertIn("高二", text)
        self.assertNotIn("item1", text)

    def test_responses_csv_shows_text_not_value(self):
        data, _, _ = survey_export.export_responses([self.q], "csv")
        text = data.decode("utf-8-sig")
        self.assertIn("高二", text)
        self.assertIn("摄影; 剪辑", text)
        self.assertNotIn("item1", text)
        self.assertNotIn("item2", text)

    def test_responses_pdf_generates(self):
        data, _, _ = survey_export.export_responses([self.q], "pdf")
        self.assertTrue(data.startswith(b"%PDF"))

    def test_palette_distinct(self):
        self.assertEqual(len(survey_export.PALETTE), len(set(survey_export.PALETTE)))
        self.assertGreaterEqual(len(survey_export.PALETTE), 8)


def _class_choices():
    return [{"value": f"item{i}", "text": str(i)} for i in range(1, 9)]


def _nested_schema():
    """「选项内子题」：选中某选项时就地展开子题（SurveyJS ``choices[i].elements``）。"""
    return {
        "title": "嵌套问卷",
        "pages": [{
            "name": "p1",
            "elements": [
                {"type": "radiogroup", "name": "join", "title": "是否参加", "choices": [
                    {"value": "item1", "text": "否"},
                    {"value": "item2", "text": "是", "elements": [
                        {"type": "text", "name": "stuname", "title": "你的姓名"},
                        {"type": "radiogroup", "name": "grade", "title": "你的年级", "choices": [
                            {"value": "item1", "text": "高一", "elements": [
                                {"type": "dropdown", "name": "class1", "title": "班级",
                                 "choices": _class_choices()},
                            ]},
                            {"value": "item2", "text": "高二", "elements": [
                                {"type": "dropdown", "name": "class2", "title": "班级",
                                 "choices": _class_choices()},
                            ]},
                        ]},
                        {"type": "boolean", "name": "member", "title": "你是否为社员"},
                    ]},
                ]},
                {"type": "text", "name": "tail", "title": "意见"},
            ],
        }],
    }


class SurveyNestedChoiceExportTest(TestCase):
    """回归：「选项内子题」缺失导致导出只剩父题一列（PR：fix/survey-export-nested-questions）。"""

    def setUp(self):
        self.schema = _nested_schema()
        self.q = Questionnaire.objects.create(kind=Questionnaire.KIND_SURVEY, schema=self.schema)
        QuestionnaireResponse.objects.create(
            questionnaire=self.q,
            answers={
                "join": "item2", "stuname": "夏轩逸", "grade": "item2",
                "class2": "item7", "member": True, "tail": "无",
            },
        )
        QuestionnaireResponse.objects.create(
            questionnaire=self.q,
            answers={"join": "item1", "tail": "不参加"},
        )

    def test_extract_walks_choice_nested_questions(self):
        names = [q["name"] for q in survey_export.extract_questions(self.schema)]
        # 子题紧跟父题之后，且嵌套层级按展开顺序摊平
        self.assertEqual(
            names,
            ["join", "stuname", "grade", "class1", "class2", "member", "tail"],
        )

    def test_duplicate_titles_get_parent_prefix(self):
        qs = {q["name"]: q for q in survey_export.extract_questions(self.schema)}
        self.assertEqual(qs["class1"]["title"], "高一 / 班级")
        self.assertEqual(qs["class2"]["title"], "高二 / 班级")
        self.assertEqual(qs["grade"]["title"], "你的年级")  # 不重名的不动
        self.assertEqual(qs["stuname"]["path"], ["是"])

    def test_responses_csv_includes_nested_columns(self):
        data, _, _ = survey_export.export_responses([self.q], "csv")
        text = data.decode("utf-8-sig")
        header = text.splitlines()[0]
        for title in ("你的姓名", "你的年级", "高二 / 班级", "你是否为社员", "意见"):
            self.assertIn(title, header, header)
        row = next(r for r in text.splitlines() if "夏轩逸" in r)
        self.assertIn("7", row)      # 子题下拉的 option 文本被还原（item7 → 7）
        self.assertEqual(row.count("是"), 2)   # 「是」参加 + 布尔子题「是」
        self.assertNotIn("item7", text)
        self.assertNotIn("True", text)

    def test_stats_include_nested_questions(self):
        stats = survey_export.compute_stats(
            self.schema, [r.answers for r in self.q.responses.all()],
        )
        by_name = {s["name"]: s for s in stats}
        self.assertEqual(by_name["class2"]["counts"]["item7"], 1)   # 未出现的选项补零
        self.assertEqual(by_name["class2"]["counts"]["item1"], 0)
        self.assertEqual(by_name["class2"]["answered"], 1)
        self.assertEqual(by_name["class2"]["title"], "高二 / 班级")
        self.assertEqual(by_name["member"]["answers"], ["是"])

        data, _, _ = survey_export.export_stats([self.q], "csv")
        text = data.decode("utf-8-sig")
        self.assertIn("高二 / 班级", text)
        self.assertIn("你是否为社员", text)

    def test_responses_pdf_includes_nested_questions(self):
        data, content_type, _ = survey_export.export_responses([self.q], "pdf")
        self.assertEqual(content_type, "application/pdf")
        self.assertTrue(data.startswith(b"%PDF"))

    def test_same_name_twice_is_not_duplicated(self):
        schema = {
            "pages": [{
                "name": "p1",
                "elements": [{
                    "type": "radiogroup", "name": "join", "title": "参加吗",
                    "choices": [
                        {"value": "item1", "text": "是", "elements": [
                            {"type": "text", "name": "dup", "title": "说明"},
                        ]},
                        {"value": "item2", "text": "否", "elements": [
                            {"type": "text", "name": "dup", "title": "说明"},
                        ]},
                    ],
                }],
            }],
        }
        names = [q["name"] for q in survey_export.extract_questions(schema)]
        self.assertEqual(names, ["join", "dup"])

    def test_max_nest_depth_guard(self):
        leaf = {"type": "text", "name": "leaf", "title": "底"}
        node = {"type": "text", "name": "deep", "title": "深",
                "choices": [{"value": "item1", "text": "更", "elements": [leaf]}]}
        schema = {"pages": [{"name": "p1", "elements": [node]}]}
        # 正常深度能拿到子题
        self.assertIn("leaf", [q["name"] for q in survey_export.extract_questions(schema)])
        # 把一个题目的选项指回自己（畸形 schema）不能死循环
        cyclic = {"type": "text", "name": "loop", "title": "环",
                  "choices": [{"value": "item1", "text": "x", "elements": []}]}
        cyclic["choices"][0]["elements"].append(cyclic)
        names = [q["name"] for q in survey_export.extract_questions(
            {"pages": [{"name": "p1", "elements": [cyclic]}]},
        )]
        self.assertEqual(names, ["loop"])

    def test_paneldynamic_template_not_flattened(self):
        schema = {
            "pages": [{
                "name": "p1",
                "elements": [{
                    "type": "paneldynamic", "name": "rows", "title": "多条记录",
                    "templateElements": [{"type": "text", "name": "inner", "title": "行内"}],
                }],
            }],
        }
        # paneldynamic 的作答是「每行一个 dict」的列表，摊成普通列会永远为空
        # → 维持既有行为：不摊平（等真正用到时再按行展开）
        self.assertEqual(survey_export.extract_questions(schema), [])


class SurveyCsvInjectionTest(TestCase):
    """M-5 回归：以 = + - @ 开头的作答单元格加单引号，Excel 不执行公式。"""

    def setUp(self):
        self.q = Questionnaire.objects.create(kind=Questionnaire.KIND_SURVEY, schema=_schema())

    def test_formula_prefixed_answers_are_escaped(self):
        QuestionnaireResponse.objects.create(
            questionnaire=self.q,
            answers={"grade": "=HYPERLINK(\"http://evil\",\"x\")", "note": "@SUM(1,1)"},
        )
        data, _content_type, _filename = survey_export.export_responses([self.q], "csv")
        text = data.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'@SUM", text)
        self.assertNotIn("\n=HYPERLINK", text)
        self.assertNotIn(",=HYPERLINK", text)
