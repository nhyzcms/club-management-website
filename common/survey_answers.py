"""SurveyJS 作答校验（审计 M-2）。

Schema 是作者可编辑的 JSON；作答此前只要求「是 dict」，于是：

- 未知题名、错误类型、越界选项都能落库，统计 / 导出 / ``can_edit_schema``
  全被污染；
- 文件题可填任意 URL 字符串，管理端渲染成可点链接（钓鱼）。

2026-11 调整过一次键名策略：**「schema 里没有的键就整份拒绝」会把合法的
SurveyJS 特性误判成未知题目**，接口 400 且不落库，用户只看到一句
「存在未知题目」——选项内子题、``showOtherItem`` 的 ``<key>-Comment``、
``multipletext`` / ``paneldynamic`` / ``ranking`` 都踩过。现在：

- 作答键按 SurveyJS 规则完整枚举（``valueName``、选项内子题、``-Comment``、
  ``calculatedValues`` / trigger 的 ``setToName``）；
- 认不出的键**保留**并记 warning：统计与导出只按 schema 取列，多出的键不会展示，
  丢掉它们才是真丢数据；
- 必填、选项归属、文件项、单值题类型、总大小仍然校验——这些才真正会污染数据；
- 不认识的题型不再强行按单值断言，避免 SurveyJS 升级 / 新题型把正常答卷拒掉。

不解释表达式 / 可见性条件（SurveyJS 表达式无法在服务端安全求值），
隐藏的必填题允许为空——客户端会按同一 schema 跳过它。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

MAX_ANSWERS_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 20_000
# 选项内子题的最大下钻深度（防畸形 schema 自引用导致死循环；与导出侧同口径）。
MAX_NEST_DEPTH = 6

# 这些题只负责展示 / 计算，不产生作答键。
_NO_ANSWER_TYPES = frozenset({"html", "image", "expression"})
# 多值题：值必须是数组。
_MULTI_VALUE_TYPES = frozenset({"checkbox", "tagbox", "file"})
# 有 choices 的单值题（buttongroup 是 radiogroup 的别名）。
_CHOICE_TYPES = frozenset({"radiogroup", "dropdown", "buttongroup"})
# 结构化题型：值必须是数组 / 对象，不能按单值断言。
_LIST_VALUE_TYPES = frozenset({"paneldynamic", "ranking"})
_DICT_VALUE_TYPES = frozenset({"multipletext"})
# 已知的单值题型：只有这些才断言「不能是 dict / list」。
# 不在这里的题型一律不猜——新题型宁可放过，也不要整份拒掉。
_SINGLE_VALUE_TYPES = frozenset({
    "text", "comment", "signaturepad", "color",
    "slider", "nouislider", "range",
})


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


def _allowed_values(question: dict) -> set[str] | None:
    """合法选项集合；``None`` 表示 schema 没定义 choices、不做归属校验。

    ``showOtherItem`` / ``showNoneItem`` 会让 SurveyJS 追加「其他」/「以上都不是」，
    提交的值是 ``other`` / ``none``，不在 choices 里。
    """
    choices = question.get("choices")
    if not choices:
        return None
    allowed = _choice_values(choices)
    if question.get("showOtherItem"):
        allowed.add("other")
    if question.get("showNoneItem"):
        allowed.add("none")
    return allowed


def _answer_key(element: dict) -> str:
    """题目的作答键：SurveyJS 用 ``valueName`` 覆盖 ``name``。"""
    key = element.get("valueName")
    if key is None or key == "":
        key = element.get("name")
    return "" if key is None else str(key)


def _collect_questions(
    schema: dict,
) -> tuple[dict[str, dict], dict[str, tuple[str, str]], set[str]]:
    """收集 ``作答键 -> 题目定义``、选项内子题的激活条件、以及额外合法键。

    作答键的来源：

    - 普通题：``valueName``（优先）或 ``name``；
    - **选项内子题**：SurveyJS 允许在 ``choices[i].elements`` 挂子题，选中该选项时
      就地展开（如「会员＝是」→「姓名」）。作答按子题自己的键平铺在 answers 里，
      和导出侧 ``activities.survey_export.extract_questions`` 同口径；
    - ``<key>-Comment``：``showOtherItem``（选项含「其他」）或 ``showCommentArea``；
    - ``calculatedValues``（``includeIntoResult``）与 trigger 的 ``setToName``。

    ``guards[key] = (父题键, 选项值)``：只有父题答案等于该选项（多选则包含）时，
    这题才可见、才该被要求必填。

    ``paneldynamic`` 的 ``templateElements`` 不展开：它的作答是「每行一个 dict」
    的列表，内层键不是顶层作答键。
    """
    questions: dict[str, dict] = {}
    guards: dict[str, tuple[str, str]] = {}
    extra_keys: set[str] = set()

    def walk(elements, guard=None, depth: int = 0) -> None:
        if depth > MAX_NEST_DEPTH or not isinstance(elements, list):
            return
        for element in elements:
            if not isinstance(element, dict):
                continue
            key = _answer_key(element)
            if key and key not in questions:
                # 同一个作答键只取先出现的（按页面顺序），与导出侧一致。
                questions[key] = element
                if guard is not None:
                    guards[key] = guard
                if element.get("showOtherItem") or element.get("showCommentArea"):
                    extra_keys.add(f"{key}-Comment")
            # panel 的题在 elements 里；matrix 的列不是独立作答键。
            if isinstance(element.get("elements"), list):
                walk(element["elements"], guard, depth + 1)
            # 选项内子题：激活条件绑到「这个题的这个选项」。
            if not key:
                continue
            for choice in element.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                if not isinstance(choice.get("elements"), list):
                    continue
                value = choice.get("value", choice.get("text"))
                if value is None:
                    continue
                walk(choice["elements"], (key, str(value)), depth + 1)

    for page in schema.get("pages") or []:
        if isinstance(page, dict):
            walk(page.get("elements"))

    for calc in schema.get("calculatedValues") or []:
        if isinstance(calc, dict) and calc.get("includeIntoResult") and calc.get("name"):
            extra_keys.add(str(calc["name"]))
    for trigger in schema.get("triggers") or []:
        if isinstance(trigger, dict) and trigger.get("setToName"):
            extra_keys.add(str(trigger["setToName"]))

    return questions, guards, extra_keys


def _is_active(key: str, guards: dict[str, tuple[str, str]], answers: dict) -> bool:
    """「选项内子题」是否被父题的选择激活；无激活条件（普通题）恒为真。

    父选项没选中时，SurveyJS 会把子题的值从 data 里清掉。这类子题即使
    ``isRequired`` 也不该报「必填」，否则「否」分支永远交不上来。
    """
    guard = guards.get(key)
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


def validate_answers(schema: dict, answers: dict, *, context: str = "") -> dict:
    """校验并原样返回作答；不合法 raise ``InvalidSurveyAnswers``。

    ``context`` 只用于日志定位（活动 / 问卷 / 用户），不参与校验。
    """
    if not isinstance(answers, dict):
        raise InvalidSurveyAnswers("answers 须为 JSON 对象")
    try:
        encoded = json.dumps(answers, ensure_ascii=False)
    except (TypeError, ValueError):
        raise InvalidSurveyAnswers("answers 含无法序列化的值") from None
    if len(encoded.encode("utf-8")) > MAX_ANSWERS_BYTES:
        raise InvalidSurveyAnswers("answers 体积过大")

    questions, guards, extra_keys = _collect_questions(schema if isinstance(schema, dict) else {})
    if not questions:
        # 兼容历史「默认空问卷」：没有题目定义时无从校验键名，保持原行为。
        return answers
    unknown = [key for key in answers if key not in questions and key not in extra_keys]
    if unknown:
        # 不再整份拒绝：认不出的键保留，只留一条日志便于发现 schema 没覆盖的合法特性。
        logger.warning(
            "问卷作答含 schema 外的键（已保留）：%s keys=%s",
            context or "-", unknown[:10],
        )

    for key, question in questions.items():
        qtype = str(question.get("type") or "")
        value = answers.get(key)
        if qtype in _NO_ANSWER_TYPES:
            continue
        if _is_empty(value):
            if question.get("isRequired") and _is_active(key, guards, answers):
                raise InvalidSurveyAnswers(f"「{key}」为必填项")
            continue

        if qtype in _MULTI_VALUE_TYPES:
            if not isinstance(value, list):
                raise InvalidSurveyAnswers(f"「{key}」应为数组")
            if len(value) > 200:
                raise InvalidSurveyAnswers(f"「{key}」选项过多")
            if qtype in ("checkbox", "tagbox"):
                allowed = _allowed_values(question)
                if allowed and any(str(item) not in allowed for item in value):
                    raise InvalidSurveyAnswers(f"「{key}」包含无效选项")
            elif qtype == "file":
                for item in value:
                    if not isinstance(item, (str, dict)):
                        raise InvalidSurveyAnswers(f"「{key}」文件项格式无效")
            continue

        if qtype in _CHOICE_TYPES:
            allowed = _allowed_values(question)
            if isinstance(value, (dict, list)):
                raise InvalidSurveyAnswers(f"「{key}」应为单值")
            if allowed and str(value) not in allowed:
                raise InvalidSurveyAnswers(f"「{key}」包含无效选项")
            continue

        if qtype == "boolean":
            if not isinstance(value, bool):
                raise InvalidSurveyAnswers(f"「{key}」应为布尔值")
            continue

        if qtype == "rating":
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise InvalidSurveyAnswers(f"「{key}」评分格式无效")
            continue

        if qtype in ("matrix", "matrixdropdown", "matrixdynamic"):
            if not isinstance(value, (dict, list)):
                raise InvalidSurveyAnswers(f"「{key}」矩阵作答格式无效")
            continue

        if qtype in _LIST_VALUE_TYPES:
            if not isinstance(value, list):
                raise InvalidSurveyAnswers(f"「{key}」应为数组")
            continue

        if qtype in _DICT_VALUE_TYPES:
            if not isinstance(value, dict):
                raise InvalidSurveyAnswers(f"「{key}」格式无效")
            continue

        if qtype in _SINGLE_VALUE_TYPES:
            _validate_scalar(key, value)
        # 其它题型（含将来新增的）：不猜结构，只受上面的可序列化 / 总大小约束。

    return answers
