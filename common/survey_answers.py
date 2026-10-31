"""SurveyJS 作答校验（审计 M-2）。

Schema 是作者可编辑的 JSON；作答此前只要求「是 dict」，于是：

- 未知题名、错误类型、越界选项都能落库，统计 / 导出 / ``can_edit_schema``
  全被污染；
- 文件题可填任意 URL 字符串，管理端渲染成可点链接（钓鱼）。

本模块只做**结构性**校验：必填、类型、选项归属、未知键、总大小。
不解释表达式 / 可见性条件（SurveyJS 表达式无法在服务端安全求值），
``visibleIf`` 隐藏的必填题允许为空——客户端会按同一 schema 跳过它。
"""
from __future__ import annotations

import json

MAX_ANSWERS_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 20_000

# 这些题只负责展示 / 计算，不产生作答键。
_NO_ANSWER_TYPES = frozenset({"html", "image", "expression"})
# 多值题。
_MULTI_VALUE_TYPES = frozenset({"checkbox", "tagbox", "file"})
# 有 choices 的单值题。
_CHOICE_TYPES = frozenset({"radiogroup", "dropdown"})


class InvalidSurveyAnswers(ValueError):
    """作答不符合 Schema；``str(self)`` 给视图当 400 文案。"""


def _choice_values(choices) -> set[str]:
    values: set[str] = set()
    for choice in choices or []:
        if isinstance(choice, dict):
            value = choice.get("value")
            if value is not None:
                values.add(str(value))
        elif choice is not None:
            values.add(str(choice))
    return values


def _collect_questions(schema: dict) -> dict[str, dict]:
    """递归收集 ``name -> 题目定义``（支持 panel / paneldynamic 的 elements）。"""
    found: dict[str, dict] = {}

    def walk(elements) -> None:
        if not isinstance(elements, list):
            return
        for element in elements:
            if not isinstance(element, dict):
                continue
            name = element.get("name")
            if isinstance(name, str) and name:
                found[name] = element
            # panel 的题在 elements 里；matrix 的列不是独立作答键。
            if isinstance(element.get("elements"), list):
                walk(element["elements"])

    for page in schema.get("pages") or []:
        if isinstance(page, dict):
            walk(page.get("elements"))
    return found


def _is_empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _validate_scalar(name: str, value) -> None:
    if isinstance(value, (dict, list)):
        raise InvalidSurveyAnswers(f"「{name}」应为单值")
    if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
        raise InvalidSurveyAnswers(f"「{name}」内容过长（上限 {MAX_TEXT_LENGTH} 字）")


def validate_answers(schema: dict, answers: dict) -> dict:
    """校验并原样返回作答；不合法 raise ``InvalidSurveyAnswers``。"""
    if not isinstance(answers, dict):
        raise InvalidSurveyAnswers("answers 须为 JSON 对象")
    try:
        encoded = json.dumps(answers, ensure_ascii=False)
    except (TypeError, ValueError):
        raise InvalidSurveyAnswers("answers 含无法序列化的值") from None
    if len(encoded.encode("utf-8")) > MAX_ANSWERS_BYTES:
        raise InvalidSurveyAnswers("answers 体积过大")

    questions = _collect_questions(schema if isinstance(schema, dict) else {})
    if not questions:
        # 兼容历史「默认空问卷」：没有题目定义时无从校验键名，保持原行为。
        return answers
    unknown = [key for key in answers if key not in questions]
    if unknown:
        raise InvalidSurveyAnswers(f"存在未知题目：{unknown[0]}")

    for name, question in questions.items():
        qtype = str(question.get("type") or "")
        value = answers.get(name)
        if qtype in _NO_ANSWER_TYPES:
            continue
        if _is_empty(value):
            if question.get("isRequired"):
                raise InvalidSurveyAnswers(f"「{name}」为必填项")
            continue

        if qtype in _MULTI_VALUE_TYPES:
            if not isinstance(value, list):
                raise InvalidSurveyAnswers(f"「{name}」应为数组")
            if len(value) > 200:
                raise InvalidSurveyAnswers(f"「{name}」选项过多")
            if qtype in ("checkbox", "tagbox"):
                allowed = _choice_values(question.get("choices"))
                if allowed and any(str(item) not in allowed for item in value):
                    raise InvalidSurveyAnswers(f"「{name}」包含无效选项")
            elif qtype == "file":
                for item in value:
                    if not isinstance(item, (str, dict)):
                        raise InvalidSurveyAnswers(f"「{name}」文件项格式无效")
            continue

        if qtype in _CHOICE_TYPES:
            allowed = _choice_values(question.get("choices"))
            if isinstance(value, (dict, list)):
                raise InvalidSurveyAnswers(f"「{name}」应为单值")
            if allowed and str(value) not in allowed:
                raise InvalidSurveyAnswers(f"「{name}」包含无效选项")
            continue

        if qtype == "boolean":
            if not isinstance(value, bool):
                raise InvalidSurveyAnswers(f"「{name}」应为布尔值")
            continue

        if qtype == "rating":
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise InvalidSurveyAnswers(f"「{name}」评分格式无效")
            continue

        if qtype in ("matrix", "matrixdropdown", "matrixdynamic"):
            if not isinstance(value, (dict, list)):
                raise InvalidSurveyAnswers(f"「{name}」矩阵作答格式无效")
            continue

        _validate_scalar(name, value)

    return answers
