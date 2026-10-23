"""姓名排序：**拼音首字母**（姓氏读音）+ GB2312 音序 tie-break（ADR-0025）。

识别码的「姓名排序序号」按姓名**首字母**分配：同一届（当次导入）内 A→Z 排下来，
补录时接着已有最大序号继续。本模块只做排序，不碰数据库、零第三方依赖
（服务器只有 2 GB 内存，不为排序引入拼音库）。

首字母怎么来：

1. **GB2312 一级汉字**（``B0A1``–``D7F9``，3755 字）本身就按拼音排序，所以拿 23 个
   字母段的**起始字**当边界，就能由汉字字节位置反推读音首字母——覆盖几乎所有
   常见姓名用字。边界由「相邻字」交叉验证过：每段前一字恰是上一段末字
   （澳 / 怖 / 错 / 堕 / 贰 / 咐 / 过 / 祸 / 骏 / 阔 / 络 / 穆 / 诺 / 沤 / 瀑 / 群 / 弱 /
   所 / 唾 / 误 / 迅 / 孕），说明边界取的是段首而非段中。
2. **多音字姓氏**：GB2312 把这个字放在**常用读音**的位置，当姓氏时读音不同——
   单（dān→shàn）/ 解（jiě→xiè）/ 查（chá→zhā）/ 仇（chóu→qiú）/ 区（qū→ōu）/
   乐（lè→yuè）/ 尉（wèi→yù）/ 种（zhǒng→chóng）/ 句（jù→gōu）/ 秘（mì→bì）/
   繁（fán→pó）/ 折（zhé→shé）/ 召（zhào→shào）。
3. **二级字区姓氏**（``D8A1`` 起按部首排序，位置不含读音信息）：覃 缪 隗 佘 冼 邝
   逯 郗 璩 濮 扈 钭 訾 阚 蒯 缑 禤 仉 呙 芈 郤 厍 郜 亓 仝 弋 郏。
   2、3 两类一律走 :data:`SURNAME_INITIALS` 覆盖表（显式写死，可读可测）。
4. **并列**：同首字母内按 GBK 字节序（一级字区与拼音同序，等价于「首字母相同再按拼音细排」）。
5. **判不出首字母**（生僻字、符号、数字、非汉字）：归入「未知」桶，排在所有有首字母的
   姓名之后；桶内仍按字节序，顺序稳定可复现。

已知取舍：复姓按**首字读音**排（尉迟→Y、长孙→Z……）；只有读音与首字本音不同的复姓
（单于 Chán、万俟 Mò、澹台 Tán）单列在 :data:`COMPOUND_SURNAME_INITIALS`。
"""
from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")

# GB2312 一级汉字区（B0A1「啊」– D7F9「座」，3755 字，按拼音排序）。
_LEVEL1_START = b"\xb0\xa1"
_LEVEL1_END = b"\xd7\xf9"

# 每个拼音字母段的**起始字**（段首字；没有 I / U / V 段）。
_BOUNDARY_CHARS: tuple[tuple[str, str], ...] = (
    ("A", "啊"), ("B", "芭"), ("C", "擦"), ("D", "搭"), ("E", "蛾"),
    ("F", "发"), ("G", "噶"), ("H", "哈"), ("J", "击"), ("K", "喀"),
    ("L", "垃"), ("M", "妈"), ("N", "拿"), ("O", "哦"), ("P", "啪"),
    ("Q", "期"), ("R", "然"), ("S", "撒"), ("T", "塌"), ("W", "挖"),
    ("X", "昔"), ("Y", "压"), ("Z", "匝"),
)
_BOUNDARIES: tuple[tuple[str, bytes], ...] = tuple(
    (letter, ch.encode("gbk")) for letter, ch in _BOUNDARY_CHARS
)

# 姓名用字读音与「该字在 GB2312 中的位置」不一致的姓氏（多音字姓氏 + 二级字区姓氏）。
SURNAME_INITIALS: dict[str, str] = {
    # 多音字：姓氏读音 ≠ 常用读音
    "单": "S", "解": "X", "查": "Z", "仇": "Q", "区": "O", "乐": "Y",
    "尉": "Y", "种": "C", "句": "G", "秘": "B", "繁": "P", "折": "S", "召": "S",
    # GB2312 二级字区（按部首排序，位置无读音）
    "覃": "Q", "缪": "M", "隗": "W", "佘": "S", "冼": "X", "邝": "K",
    "逯": "L", "郗": "X", "璩": "Q", "濮": "P", "扈": "H", "钭": "T",
    "訾": "Z", "阚": "K", "蒯": "K", "缑": "G", "禤": "X", "仉": "Z",
    "呙": "G", "芈": "M", "郤": "X", "厍": "S", "郜": "G", "亓": "Q",
    "仝": "T", "弋": "Y", "郏": "J",
}

# 读音与首字本音不同的复姓（其余复姓按首字读音即可：欧阳→O、尉迟→Y）。
COMPOUND_SURNAME_INITIALS: dict[str, str] = {
    "单于": "C",   # Chányú，不是 shàn
    "万俟": "M",   # Mòqí，不是 wàn
    "澹台": "T",   # Tántái，不是 dàn
    "长孙": "Z",   # Zhǎngsūn，不是 cháng
}


def _gbk(ch: str) -> bytes | None:
    """单字 GBK 编码（非 GBK 字 / 非双字节返回 None）。"""
    try:
        raw = ch.encode("gbk")
    except UnicodeEncodeError:
        return None
    return raw if len(raw) == 2 else None


def _utf8(ch: str) -> bytes:
    try:
        return ch.encode("utf-8")
    except UnicodeEncodeError:  # 孤立代理项之类：给个稳定值，绝不抛
        return ch.encode("utf-8", "surrogatepass")


def _clean(name: str) -> str:
    """排序前的姓名归一：去掉全部空白（含全角空格），保留西文大小写。"""
    return _WS_RE.sub("", (name or "").replace("\u3000", " "))


def _initial_from_gb2312(ch: str) -> str:
    """由 GB2312 一级字区的字节位置反推读音首字母；二级字 / 非汉字返回 ""。"""
    code = _gbk(ch)
    if code is None or not (_LEVEL1_START <= code <= _LEVEL1_END):
        return ""
    letter = ""
    for candidate, start in _BOUNDARIES:
        if code >= start:
            letter = candidate
        else:
            break
    return letter


def surname_initial(name: str) -> str:
    """姓名首字母（姓氏拼音首字母，A-Z）；无法判定返回空串。"""
    text = _clean(name)
    if not text:
        return ""
    for compound, letter in COMPOUND_SURNAME_INITIALS.items():
        if text.startswith(compound):
            return letter
    head = text[0]
    if head in SURNAME_INITIALS:
        return SURNAME_INITIALS[head]
    if head.isascii() and head.isalpha():  # 英文名按字母本身归位
        return head.upper()
    return _initial_from_gb2312(head)


def name_order_bytes(name: str) -> bytes:
    """排序用字节串：逐字 GBK（二级字区也是稳定的字节序），非 GBK 字用 UTF-8 兜底。"""
    out = bytearray()
    for ch in _clean(name):
        raw = _gbk(ch)
        out += raw if raw is not None else b"\xff\xff" + _utf8(ch)
    return bytes(out)


def name_sort_key(name: str) -> tuple[int, str, bytes]:
    """排序键 ``(桶, 首字母, 字节序)``。

    桶 0 = 首字母已知（A→Z 排列）；桶 1 = 判不出首字母（排最后、桶内仍稳定）。
    直接用于 ``sorted()`` / ``list.sort()``，例如::

        >>> [n for n in sorted(["张伟", "单田芳", "李四"], key=name_sort_key)]
        ['李四', '单田芳', '张伟']
    """
    initial = surname_initial(name)
    return (0 if initial else 1, initial, name_order_bytes(name))
