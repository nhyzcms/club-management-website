"""SurveyJS Schema 校验接缝（自我介绍问卷与调研共用）。"""
from django.test import SimpleTestCase

from common.survey_schema import InvalidSurveySchema, validate_schema_dict


class ValidateSchemaDictTest(SimpleTestCase):
    def test_accepts_dict_with_pages(self):
        schema = {"title": "T", "pages": [{"name": "page1", "elements": []}]}
        self.assertIs(validate_schema_dict(schema), schema)

    def test_rejects_non_dict(self):
        with self.assertRaises(InvalidSurveySchema) as ctx:
            validate_schema_dict(["pages"])
        self.assertEqual(str(ctx.exception), "问卷 Schema 须为 JSON 对象")

    def test_rejects_missing_pages(self):
        with self.assertRaises(InvalidSurveySchema) as ctx:
            validate_schema_dict({"title": "无 pages"})
        self.assertEqual(str(ctx.exception), "Schema 须包含 pages 数组")

    def test_rejects_empty_pages(self):
        with self.assertRaises(InvalidSurveySchema) as ctx:
            validate_schema_dict({"pages": []})
        self.assertEqual(str(ctx.exception), "Schema 须包含 pages 数组")

    # ---- S-4：Schema 是用户提交的数据，SurveyJS 会把其中若干字段当 HTML 渲染 ----
    def test_rejects_html_question(self):
        """html 题被 SurveyJS 原样塞进 dangerouslySetInnerHTML，直接拒。"""
        schema = {"pages": [{"elements": [{"type": "html", "html": "<img src=x onerror=alert(1)>"}]}]}
        with self.assertRaises(InvalidSurveySchema) as ctx:
            validate_schema_dict(schema)
        self.assertIn("html 题", str(ctx.exception))

    def test_rejects_nested_html_question(self):
        """藏在 panel / 嵌套 pages 里的 html 题同样要拒。"""
        schema = {
            "pages": [{"elements": [
                {"type": "panel", "elements": [{"type": "html", "html": "<script>x</script>"}]},
            ]}],
        }
        with self.assertRaises(InvalidSurveySchema):
            validate_schema_dict(schema)

    def test_scrubs_completed_html(self):
        """completedHtml 里的脚本 / 事件处理器被剥，正常内容保留。"""
        schema = {
            "pages": [{"elements": [{"type": "text", "name": "a"}]}],
            "completedHtml": '<script>alert(1)</script><p onclick="x()">提交成功</p><img src=x onerror=1>',
        }
        out = validate_schema_dict(schema)
        self.assertNotIn("<script", out["completedHtml"])
        self.assertNotIn("onclick", out["completedHtml"])
        self.assertNotIn("onerror", out["completedHtml"])
        self.assertIn("提交成功", out["completedHtml"])

    def test_accepts_normal_survey(self):
        schema = {
            "pages": [{"name": "p1", "elements": [
                {"type": "text", "name": "q1", "title": "姓名"},
                {"type": "radiogroup", "name": "q2", "choices": ["a", "b"]},
            ]}],
            "completedHtml": "<p>谢谢参与</p>",
        }
        out = validate_schema_dict(schema)
        self.assertEqual(len(out["pages"][0]["elements"]), 2)
        self.assertIn("谢谢参与", out["completedHtml"])
