"""旧浏览器只读版的富文本清洗。

与主站 common.rich_text.sanitize_html 的目标不同：主站要让现代浏览器里的
富文本「尽量还原」，这里宁可少留——旧浏览器解析器老、XSS 面更大，
所以内联样式、脚本、iframe、第三方图片一律不留。
"""

import re
from html import escape
from urllib.parse import urlsplit

import bleach

ALLOWED_TAGS = [
    "p", "br", "hr", "strong", "b", "em", "i", "u", "s", "del", "sub", "sup",
    "h2", "h3", "h4", "blockquote", "ul", "ol", "li",
    "a", "img", "figure", "figcaption", "span", "code", "pre",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
]
ALLOWED_ATTRS = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]

# script / style / iframe 等整块删除：bleach 的 strip=True 只剥标签、保留文字，
# 脚本源码会被当成正文显示出来。
_DROP_BLOCK_RE = re.compile(
    r"<(script|style|iframe|object|embed|video|audio|canvas|svg|noscript)\b.*?</\1\s*>",
    re.I | re.S,
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_SRC_RE = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def _is_same_origin(src):
    """只内嵌站内资源（/media/…、/static/… 和其它以 / 开头的站内路径）。"""
    value = (src or "").strip()
    if not value:
        return False
    if value.startswith("//") or _SCHEME_RE.match(value):
        return False
    return value.startswith("/")


def _host_of(src):
    try:
        parts = urlsplit(src)
    except ValueError:
        return ""
    return parts.netloc or parts.path


def _placeholder(src):
    host = _host_of(src) or "外部站点"
    return (
        '<div class="legacy-extimg">'
        "外链图片未自动加载：" + escape(host)
        + '<br><a href="' + escape(src, quote=True) + '" target="_blank" rel="nofollow noopener noreferrer">'
        "在新窗口查看（可能向该站暴露你的 IP 与访问时间）</a></div>"
    )


def sanitize_legacy_html(html):
    """清洗正文，返回 (安全 HTML, 被拦下的外链图片张数)。"""
    if not html:
        return "", 0
    text = _COMMENT_RE.sub("", html)
    text = _DROP_BLOCK_RE.sub("", text)
    cleaned = bleach.clean(
        text,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )

    external = [0]

    def replace(match):
        tag = match.group(0)
        found = _SRC_RE.search(tag)
        src = ""
        if found:
            src = (found.group(1) or found.group(2) or found.group(3) or "").strip()
        if not src or _is_same_origin(src):
            return tag
        external[0] += 1
        return _placeholder(src)

    cleaned = _IMG_RE.sub(replace, cleaned)
    return cleaned, external[0]
