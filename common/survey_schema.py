"""门户 SurveyJS Schema 校验。自我介绍问卷与调研共用同一规则（ADR 0011 / 0014）。

安全约束（2026-10-31 审计 S-4）
==============================

Schema 是**用户提交的数据**，而 SurveyJS 会把下面这些字段原样塞进
``dangerouslySetInnerHTML``：

- ``html`` 题的 ``html`` 属性；
- 根 / 页级的 ``completedHtml``、``completedBeforeHtml``、``loadingHtml``、
  ``emptySurveyText``。

原先只校验「有 ``pages`` 键」，等于把任意 HTML/JS 交给渲染层：作者提交一份正常问卷
过审后，在开放且零作答时把 schema 换成 ``<img src=x onerror=...>``，公开调研页就会
对每一个访客（含管理员查看作答的页面）执行脚本。

因此这里做三件事：

1. **禁止** ``type: "html"`` 题 —— 它在产品里没有正当用途，却是最直接的注入点；
2. 对上面几个富文本字段跑 :func:`common.rich_text.sanitize_html`（bleach 白名单，
   剥 script / 事件处理器 / ``javascript:`` / 同源 iframe）；
3. 递归深度与节点数设上限，避免超大 Schema 拖垮校验和渲染。
"""

from common.rich_text import sanitize_html


class InvalidSurveySchema(ValueError):
    """``validate_schema_dict`` 拒绝；``str(self)`` 给序列化器当校验文案。"""


# 会被 SurveyJS 当 HTML 渲染的字段名（根级 / 页级 / 题级通用）。
_HTML_FIELDS = frozenset({
    "html",
    "completedHtml",
    "completedBeforeHtml",
    "loadingHtml",
    "emptySurveyText",
})

# 递归上限：够深以覆盖 pages→elements→choices/templates，又能挡住构造的深层嵌套。
_MAX_DEPTH = 16
_MAX_NODES = 4000


def _walk(node, *, depth=0, counter=None):
    """遍历 schema；命中 html 题或超限时 raise，富文本字段就地清洗。"""
    if counter is None:
        counter = [0]
    if depth > _MAX_DEPTH:
        raise InvalidSurveySchema("问卷结构嵌套过深")

    if isinstance(node, dict):
        counter[0] += 1
        if counter[0] > _MAX_NODES:
            raise InvalidSurveySchema("问卷结构过大")
        if node.get("type") == "html":
            # 产品里不需要 html 题；留着就等于开放一个 HTML 注入面。
            raise InvalidSurveySchema("问卷不支持 html 题")
        for key, value in node.items():
            if isinstance(value, str) and key in _HTML_FIELDS:
                node[key] = sanitize_html(value)
            else:
                _walk(value, depth=depth + 1, counter=counter)
    elif isinstance(node, list):
        for item in node:
            _walk(item, depth=depth + 1, counter=counter)


def validate_schema_dict(value):
    """Schema 须为含非空 ``pages`` 数组的 JSON 对象，且不含 HTML 注入面。

    非法则 raise ``InvalidSurveySchema``。返回（可能已被清洗过的）同一个对象。
    """
    if not isinstance(value, dict):
        raise InvalidSurveySchema("问卷 Schema 须为 JSON 对象")
    pages = value.get("pages")
    if not isinstance(pages, list) or not pages:
        raise InvalidSurveySchema("Schema 须包含 pages 数组")
    _walk(value)
    return value
