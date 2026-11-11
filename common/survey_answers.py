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
# 选项内子题的最大下钻深度（防畸形 schema 自引用导致死循环；与导出侧同口径）。
MAX_NEST_DEPTH = 6

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


def _collect_questions(schema: dict) -> tuple[dict[str, dict], dict[str, tuple[str, str]]]:
    """递归收集 ``name -> 题目定义``，并记下「选项内子题」的激活条件。

    嵌套来源：

    - 页面的 ``elements`` 与 ``panel`` 容器的 ``elements``；
    - **选项内子题**：SurveyJS 允许在 ``choices[i].elements`` 挂子题，选中该选项时
      就地展开（如「会员＝是」→「姓名」）。作答按子题自己的 ``name`` 平铺在
      answers 里，和导出侧 ``activities.survey_export.extract_questions`` 同口径；
      漏掉这一层会把正常答卷误判成「存在未知题目」。

    ``guards[name] = (父题 name, 选项值)``：只有父题答案等于该选项（多选则包含）
    时，这题才可见、才该被要求必填。

    ``paneldynamic`` 的 ``templateElements`` 不展开：它的作答是「每行一个 dict」
    的列表，内层键不是顶层作答键。
    """
    questions: dict[str, dict] = {}
    guards: dict[str, tuple[str, str]] = {}

    def walk(elements, guard=None, depth: int = 0) -> None:
        if depth > MAX_NEST_DEPTH or not isinstance(elements, list):
            return
        for element in elements:
            if not isinstance(element, dict):
                continue
            name = element.get("name")
            if isinstance(name, str) and name and name not in questions:
                # 同名题目只取先出现的（按页面顺序），与导出侧一致。
                questions[name] = element
                if guard is not None:
                    guards[name] = guard
            # panel 的题在 elements 里；matrix 的列不是独立作答键。
            if isinstance(element.get("elements"), list):
                walk(element["elements"], guard, depth + 1)
            # 选项内子题：激活条件绑到「这个题的这个选项」。
            if not isinstance(name, str) or not name:
                continue
            for choice in element.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                if not isinstance(choice.get("elements"), list):
                    continue
                value = choice.get("value", choice.get("text"))
                if value is None:
                    continue
                walk(choice["elements"], (name, str(value)), depth + 1)

    for page in schema.get("pages") or []:
        if isinstance(page, dict):
            walk(page.get("elements"))
    return questions, guards


def _is_active(name: str, guards: dict[str, tuple[str, str]], answers: dict) -> bool:
    """「选项内子题」是否被父题的选择激活；无激活条件（普通题）恒为真。

    父选项没选中时，SurveyJS 会把子题的值从 data 里清掉。这类子题即使
    ``isRequired`` 也不该报「必填」，否则「否」分支永远交不上来。
    """
    guard = guards.get(name)
    if guard is None:
        return True
    parent, value = guard
    parent_value = answers.get(parent)
    if isinstance(parent_value, list):
        return value in {str(item) for item in parent_value}
    return parent_value is not None and str(parent_value) == value


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

    questions, guards = _collect_questions(schema if isinstance(schema, dict) else {})
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
            if question.get("isRequired") and _is_active(name, guards, answers):
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
