"""旧浏览器只读版的富文本清洗。

与主站 common.rich_text.sanitize_html 的目标不同：主站要让现代浏览器里的
富文本「尽量还原」，这里宁可少留——旧浏览器解析器老、XSS 面更大，
所以内联样式、脚本、iframe、第三方图片一律不留。

图片的三种处理：
1. 同源（相对路径，或主机名与本站相同的绝对地址）→ 原样内嵌，只把
   绝对地址归一成路径，避免老浏览器多做一次 DNS / 连接；
2. 跨域 → 换成「未自动加载」的文字占位（不代理、不泄露访客 IP）；
3. 同源但格式旧浏览器解不了（WebP / AVIF / SVG / HEIC）→ 换成文字说明，
   否则页面上是一个破图标，比没有图更糟。
"""

import re
from html import escape, unescape
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

# IE8 及更早版本解不了的图片格式：遇到这类同源图不输出 <img>。
UNSUPPORTED_IMAGE_EXTS = (".webp", ".avif", ".svg", ".heic", ".heif")

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


def bare_host(netloc):
    """netloc → 可比对的主机名：去凭证、去端口、小写、去尾点、去 www. 前缀。"""
    host = (netloc or "").strip()
    if not host:
        return ""
    host = host.rsplit("@", 1)[-1]
    host = host.split(":")[0]
    host = host.strip().strip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _attr_url(value):
    """写回属性前的转义。

    bleach 输出的属性值已经做过一次 HTML 转义（& 变成 &amp;），
    这里再 escape 一遍就成了 &amp;amp;，查询串里的参数会被改写；
    所以先 unescape 再 escape，保证只转义一次。
    """
    return escape(unescape(value), quote=True)


def _unsafe_path(value):
    """明显不能当站内路径用的写法：反斜杠（老浏览器把它当 /，就变成协议相对地址）
    与控制字符。遇到一律按跨域处理，并且不给可点的链接。"""
    return "\\" in value or any(ord(ch) < 32 for ch in value)


def _path_of(parts):
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if parts.query:
        path += "?" + parts.query
    return path


def _same_origin_path(src, own_hosts):
    """返回站内路径；跨域或危险协议返回 None。

    主站编辑在正文里插图常常写成 http://<本站域名或 IP>/media/… 这样的
    绝对地址，浏览器打开时与相对地址等效。早先只认以 / 开头的写法，
    结果自己的图被当成外链拦掉（用户报的「外链图片未自动加载：8.153.145.175」），
    所以这里按主机名比对，同源就改写成路径。
    """
    value = (src or "").strip()
    if not value:
        return None
    if value.startswith("//"):
        parts = urlsplit("http:" + value)
        return _path_of(parts) if bare_host(parts.netloc) in own_hosts else None
    if _SCHEME_RE.match(value):
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https"):
            return None
        return _path_of(parts) if bare_host(parts.netloc) in own_hosts else None
    if value.startswith("/"):
        return None if _unsafe_path(value) else value
    return None


def _host_of(src):
    try:
        parts = urlsplit(src)
    except ValueError:
        return ""
    return bare_host(parts.netloc) or (parts.path or "")


def _external_placeholder(src):
    host = "无法识别的地址" if _unsafe_path(src) else (_host_of(src) or "外部站点")
    link = ""
    if not _unsafe_path(src):
        link = (
            '<br><a href="' + _attr_url(src) + '" target="_blank" rel="nofollow noopener noreferrer">'
            "在新窗口查看（可能向该站暴露你的 IP 与访问时间）</a>"
        )
    return '<div class="legacy-extimg">外链图片未自动加载：' + escape(host) + link + '</div>'


def _format_placeholder(path):
    name = path.split("?", 1)[0]
    ext = name.rsplit(".", 1)[-1].upper() if "." in name else ""
    link = ""
    if not _unsafe_path(path):
        link = (
            '<br><a href="' + _attr_url(path) + '" target="_blank" rel="nofollow noopener noreferrer">'
            "在新窗口打开原图（可以另存后用看图软件查看）</a>"
        )
    return (
        '<div class="legacy-extimg">'
        "这张图片是 " + escape(ext or "新") + " 格式，旧版浏览器无法直接显示。" + link + "</div>"
    )


def _is_unsupported(path):
    name = path.split("?", 1)[0].lower()
    return name.endswith(UNSUPPORTED_IMAGE_EXTS)


def sanitize_legacy_html(html, own_hosts=()):
    """清洗正文，返回 (安全 HTML, 跨域图片张数, 格式不支持张数)。

    own_hosts 是本机认可的主机名集合（见 views._own_hosts），
    用来判断「本站的绝对地址」不是外链。
    """
    if not html:
        return "", 0, 0
    hosts = frozenset(bare_host(h) for h in own_hosts if h)
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
    unsupported = [0]

    def replace(match):
        tag = match.group(0)
        found = _SRC_RE.search(tag)
        raw = ""
        if found:
            raw = (found.group(1) or found.group(2) or found.group(3) or "").strip()
        if not raw:
            return tag
        path = _same_origin_path(raw, hosts)
        if path is None:
            external[0] += 1
            return _external_placeholder(raw)
        if _is_unsupported(path):
            unsupported[0] += 1
            return _format_placeholder(path)
        if path != raw:
            # 同源绝对地址 → 相对路径：少一次 DNS，也不会把主机名写进页面。
            return tag[: found.start()] + 'src="' + _attr_url(path) + '"' + tag[found.end():]
        return tag

    cleaned = _IMG_RE.sub(replace, cleaned)
    return cleaned, external[0], unsupported[0]
