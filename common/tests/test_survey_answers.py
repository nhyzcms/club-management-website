"""作答结构校验接缝：选项内子题（SurveyJS ``choices[i].elements``）。

生产回归：调研「传统文化宣传月」的题目是「问题1 你是否为成员 → 是 → 问题2 姓名」，
子题答案平铺在 answers 里；校验侧没递归 choices，整份答卷被判「存在未知题目：问题2」，
接口 400 且不落库。
"""
from django.test import SimpleTestCase

from common.survey_answers import InvalidSurveyAnswers, validate_answers

# 与生产 schema 同构（选项内挂必填子题）。
SCHEMA = {
    "pages": [{
        "name": "page1",
        "elements": [{
            "name": "问题1",
            "type": "radiogroup",
            "title": "你是否为南汇一中传媒社成员",
            "isRequired": True,
            "choices": [
                {
                    "text": "是",
                    "value": "item1",
                    "elements": [
                        {"name": "问题2", "type": "text", "title": "你的姓名", "isRequired": True},
                        {
                            "name": "问题3",
                            "type": "dropdown",
                            "title": "年级",
                            "isRequired": True,
                            "choices": [
                                {"text": "高一", "value": "item1"},
                                {"text": "高二", "value": "item3"},
                            ],
                        },
                    ],
                },
                {"text": "否", "value": "item2"},
            ],
        }],
    }],
    "title": "",
}


class NestedChoiceAnswersTest(SimpleTestCase):
    def test_nested_choice_answers_accepted(self):
        answers = {"问题1": "item1", "问题2": "张三", "问题3": "item1"}
        self.assertEqual(validate_answers(SCHEMA, answers), answers)

    def test_unselected_branch_does_not_force_nested_required(self):
        """选「否」时子题不可见，即使 isRequired 也不该拦（客户端已清空其值）。"""
        answers = {"问题1": "item2"}
        self.assertEqual(validate_answers(SCHEMA, answers), answers)

    def test_selected_branch_still_requires_nested(self):
        with self.assertRaises(InvalidSurveyAnswers) as ctx:
            validate_answers(SCHEMA, {"问题1": "item1", "问题3": "item1"})
        self.assertIn("问题2", str(ctx.exception))

    def test_nested_choice_value_still_type_checked(self):
        with self.assertRaises(InvalidSurveyAnswers) as ctx:
            validate_answers(SCHEMA, {"问题1": "item1", "问题2": ["不是单值"], "问题3": "item1"})
        self.assertIn("问题2", str(ctx.exception))

    def test_checkbox_parent_activates_selected_choices(self):
        """多选父题：只有被勾选选项下的子题才要求必填。"""
        schema = {"pages": [{"elements": [{
            "name": "p", "type": "checkbox",
            "choices": [
                {"value": "a", "elements": [{"name": "child_a", "type": "text", "isRequired": True}]},
                {"value": "b", "elements": [{"name": "child_b", "type": "text", "isRequired": True}]},
            ],
        }]}]}
        self.assertEqual(validate_answers(schema, {"p": ["a"], "child_a": "x"}), {"p": ["a"], "child_a": "x"})
        with self.assertRaises(InvalidSurveyAnswers) as ctx:
            validate_answers(schema, {"p": ["a"]})
        self.assertIn("child_a", str(ctx.exception))

    def test_two_level_nested_choice(self):
        """选项内子题还能再挂选项子题。"""
        schema = {"pages": [{"elements": [{
            "name": "outer", "type": "radiogroup",
            "choices": [{
                "value": "on", "elements": [{
                    "name": "mid", "type": "radiogroup",
                    "choices": [{"value": "m1", "elements": [
                        {"name": "deep", "type": "text", "isRequired": True},
                    ]}],
                }],
            }],
        }]}]}
        ok = {"outer": "on", "mid": "m1", "deep": "值"}
        self.assertEqual(validate_answers(schema, ok), ok)
        with self.assertRaises(InvalidSurveyAnswers) as ctx:
            validate_answers(schema, {"outer": "on", "mid": "m1"})
        self.assertIn("deep", str(ctx.exception))
        # outer 未选中时，整条分支都不要求
        self.assertEqual(validate_answers(schema, {"outer": ""}), {"outer": ""})

    def test_truly_unknown_question_still_rejected(self):
        with self.assertRaises(InvalidSurveyAnswers) as ctx:
            validate_answers(SCHEMA, {"问题1": "item2", "幽灵题": 1})
        self.assertIn("幽灵题", str(ctx.exception))

    def test_self_referencing_schema_does_not_recurse_forever(self):
        """畸形 schema 自引用：靠 MAX_NEST_DEPTH 截断，不抛 RecursionError。"""
        element = {"name": "loop", "type": "radiogroup", "choices": []}
        element["choices"].append({"value": "a", "elements": [element]})
        schema = {"pages": [{"elements": [element]}]}
        self.assertEqual(validate_answers(schema, {"loop": "a"}), {"loop": "a"})
