"""问卷作答检索：把 JSON 作答摊平成可搜索文本，供 ``GET .../responses/?q=`` 过滤。

判定放在 Python 侧，理由：

- 作答是 ``JSONField``，而「把 JSON 当文本模糊匹配」在 SQLite / PostgreSQL 上不等价
  ——Django 写 SQLite 时 ``json.dumps`` 默认 ``ensure_ascii=True``，中文会落成
  ``\\u5f20\\u4e09``，``icontains`` 永远搜不到中文；PostgreSQL 的 ``::text`` 又受
  驱动与版本影响。跨库可靠的写法是取出 JSON 在 Python 里比。
- 数据量级是社团问卷（千份量级），且该端点本来就要把每份作答整包发给前端，
  逐行扫描不增加 IO；真要上万份时再考虑落一列检索文本（那是另一个迁移）。

匹配口径：

- **只有用户填写的内容**参与匹配（作答值），不含作答者用户名 / 时间。
- 选择题按**选项展示文本**匹配——SurveyJS 允许 ``value`` 与 ``text`` 不同
  （存 ``item1``、看到「新闻」），用户搜的必然是看到的那个词。
- 文件题匹配文件名与链接；多选逐项匹配；数字 / 评分按字符串匹配。
- 归一化用 NFKC + 折叠空白 + ``casefold``：全角「ＮＥＷＳ」能搜到 "news"，
  多余空格不影响结果。

本模块只做纯计算，不做 DB 访问，便于单测。
"""

from __future__ import annotations

import re
import unicodedata

from .survey_export import CHOICE_TYPES, extract_questions

# 检索词长度上限（防御性：再长也不会是有效检索，只会拖慢逐行扫描）
MAX_QUERY_LEN = 100
# 命中片段左右各保留的字符数
SNIPPET_RADIUS = 24
# 每份作答最多回传几条命中字段（前端只做提示，不做全文高亮）
MAX_MATCHES_PER_RESPONSE = 3

_WS_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """归一化：NFKC（全角/半角统一）+ 折叠空白 + 大小写不敏感。"""
    return _WS_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip().casefold()


def clean_query(raw) -> str:
    """清洗检索词：非字符串 → 空串；去控制字符、折叠空白、限长。保留原始大小写供回显。"""
    if not isinstance(raw, str):
        return ""
    text = raw.replace("\x00", " ").strip()
    return _WS_RE.sub(" ", text)[:MAX_QUERY_LEN]


def _value_texts(value) -> list[str]:
    """把一个答案值摊平成若干字符串（列表逐项、文件对象取名称与链接）。"""
    if value is None:
        return []
    if isinstance(value, bool):
        # SurveyJS 布尔题存 true/false，界面显示「是/否」——两种都算命中
        return ["是", "true"] if value else ["否", "false"]
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_value_texts(item))
        return out
    if isinstance(value, dict):
        # 文件题 {"name": "海报.png", "content": "…"}；多填空 {"item1": "…"}
        named = [
            value.get("name"), value.get("content"), value.get("url"),
        ]
        named = [v for v in named if isinstance(v, str) and v.strip()]
        if named:
            return named
        out = []
        for item in value.values():
            out.extend(_value_texts(item))
        return out
    return [str(value)]


def _question_texts(question: dict, value) -> list[str]:
    """按题型把一个答案转成「用户看到的文本」。"""
    q_type = question.get("type") or ""
    if q_type in CHOICE_TYPES:
        labels = question.get("choice_labels") or {}
        out: list[str] = []
        for raw in (value if isinstance(value, list) else [value]):
            if raw is None or raw == "":
                continue
            key = str(raw)
            out.extend(_value_texts(labels.get(key, key)))
        return out
    return _value_texts(value)


def answer_fields(schema: dict, answers) -> list[dict]:
    """作答 → ``[{name, title, texts}]``：按 Schema 题目顺序，未登记的键附在末尾。

    Schema 里已删除题目但历史作答仍留着键是正常的（问卷只在零作答时可改，
    但导入 / 手工数据仍可能不同步），所以不丢弃未知键。
    """
    answers = answers if isinstance(answers, dict) else {}
    questions = extract_questions(schema if isinstance(schema, dict) else {})
    known = {q["name"] for q in questions}
    fields: list[dict] = []
    for question in questions:
        name = question["name"]
        if name not in answers:
            continue
        texts = _question_texts(question, answers.get(name))
        if texts:
            fields.append({
                "name": name,
                "title": question.get("title") or name,
                "texts": texts,
            })
    for name, value in answers.items():
        if name in known:
            continue
        texts = _value_texts(value)
        if texts:
            fields.append({"name": name, "title": name, "texts": texts})
    return fields


def _snippet(text: str, query: str, radius: int = SNIPPET_RADIUS) -> str:
    """取命中处前后若干字符作提示；找不到（归一化改写导致）就退回开头。"""
    flat = _WS_RE.sub(" ", text).strip()
    if not flat:
        return ""
    if len(flat) <= radius * 2 + len(query):
        return flat
    idx = flat.lower().find(query.lower())
    if idx < 0:
        idx = flat.lower().find(normalize_text(query))
    if idx < 0:
        return flat[: radius * 2] + "…"
    start = max(0, idx - radius)
    end = min(len(flat), idx + len(query) + radius)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def search_answers(schema: dict, answers, query: str) -> tuple[bool, list[dict]]:
    """判断一份作答是否命中检索词；命中则回传命中字段（最多 3 条）。

    ``query`` 应已过 :func:`clean_query`；空串视为「全部命中」（不过滤）。
    """
    needle = normalize_text(query)
    if not needle:
        return True, []
    hits: list[dict] = []
    for field in answer_fields(schema, answers):
        for text in field["texts"]:
            if needle in normalize_text(text):
                hits.append({
                    "name": field["name"],
                    "title": field["title"],
                    "snippet": _snippet(text, query),
                })
                break
    return bool(hits), hits[:MAX_MATCHES_PER_RESPONSE]
