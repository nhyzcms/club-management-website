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

    def test_truly_unknown_key_is_kept(self):
        """认不出的键不再整份拒绝：统计 / 导出按 schema 取列，多出的键不会展示。"""
        answers = {"问题1": "item2", "幽灵题": 1}
        self.assertEqual(validate_answers(SCHEMA, answers), answers)

    def test_self_referencing_schema_does_not_recurse_forever(self):
        """畸形 schema 自引用：靠 MAX_NEST_DEPTH 截断，不抛 RecursionError。"""
        element = {"name": "loop", "type": "radiogroup", "choices": []}
        element["choices"].append({"value": "a", "elements": [element]})
        schema = {"pages": [{"elements": [element]}]}
        self.assertEqual(validate_answers(schema, {"loop": "a"}), {"loop": "a"})


class ExtraAnswerKeysTest(SimpleTestCase):
    """SurveyJS 会额外产生的作答键 / 题型，不能被当成「未知题目」。"""

    def test_other_item_comment_key_accepted(self):
        """``showOtherItem``：选「其他」时文本存到 ``<key>-Comment``。"""
        schema = {"pages": [{"elements": [{
            "name": "source", "type": "dropdown", "showOtherItem": True,
            "choices": ["a", "b"],
        }]}]}
        answers = {"source": "other", "source-Comment": "社团群"}
        self.assertEqual(validate_answers(schema, answers), answers)

    def test_comment_area_key_accepted(self):
        schema = {"pages": [{"elements": [{"name": "q", "type": "text", "showCommentArea": True}]}]}
        answers = {"q": "x", "q-Comment": "补充"}
        self.assertEqual(validate_answers(schema, answers), answers)

    def test_value_name_is_the_answer_key(self):
        """``valueName`` 覆盖 ``name`` 作为作答键。"""
        schema = {"pages": [{"elements": [{
            "name": "q1", "valueName": "v1", "type": "text", "isRequired": True,
        }]}]}
        self.assertEqual(validate_answers(schema, {"v1": "x"}), {"v1": "x"})
        with self.assertRaises(InvalidSurveyAnswers) as ctx:
            validate_answers(schema, {"q1": "x"})  # 必填的 v1 缺失
        self.assertIn("v1", str(ctx.exception))

    def test_multipletext_dict_accepted(self):
        """``multipletext`` 的值是 dict：以前被「应为单值」整份拒掉。"""
        schema = {"pages": [{"elements": [{
            "name": "mt", "type": "multipletext",
            "items": [{"name": "a"}, {"name": "b"}],
        }]}]}
        answers = {"mt": {"a": "1", "b": "2"}}
        self.assertEqual(validate_answers(schema, answers), answers)

    def test_paneldynamic_and_ranking_list_accepted(self):
        schema = {"pages": [{"elements": [
            {"name": "pd", "type": "paneldynamic", "templateElements": [{"name": "x", "type": "text"}]},
            {"name": "rk", "type": "ranking", "choices": ["a", "b"]},
        ]}]}
        answers = {"pd": [{"x": "1"}], "rk": ["b", "a"]}
        self.assertEqual(validate_answers(schema, answers), answers)

    def test_calculated_value_included_in_result(self):
        schema = {
            "pages": [{"elements": [{"name": "q", "type": "text"}]}],
            "calculatedValues": [{"name": "total", "expression": "1", "includeIntoResult": True}],
        }
        answers = {"q": "x", "total": 1}
        self.assertEqual(validate_answers(schema, answers), answers)

    def test_unknown_type_is_not_forced_single_value(self):
        """新题型：不猜结构，避免 SurveyJS 升级后整份被拒。"""
        schema = {"pages": [{"elements": [{"name": "future", "type": "some-new-type"}]}]}
        answers = {"future": {"any": "shape"}}
        self.assertEqual(validate_answers(schema, answers), answers)

    def test_option_membership_still_validated(self):
        """放宽键名后，选项归属（真正的脏数据）仍要拦。"""
        schema = {"pages": [{"elements": [
            {"name": "q", "type": "radiogroup", "choices": ["A", "B"]},
        ]}]}
        with self.assertRaises(InvalidSurveyAnswers) as ctx:
            validate_answers(schema, {"q": "C"})
        self.assertIn("无效选项", str(ctx.exception))
