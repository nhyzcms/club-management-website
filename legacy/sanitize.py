"""旧浏览器只读版的富文本清洗。

与主站 common.rich_text.sanitize_html 的目标不同：主站要让现代浏览器里的
富文本「尽量还原」，这里宁可少留——旧浏览器解析器老、XSS 面更大，
所以内联样式、脚本、iframe、第三方图片一律不留。

图片的四种处理：
1. 同源（相对路径，或主机名与本站相同的绝对地址）→ 原样内嵌，只把
   绝对地址归一成路径，避免老浏览器多做一次 DNS / 连接；
2. 跨域 → 换成「未自动加载」的文字占位（不代理、不泄露访客 IP）；
3. 同源、格式旧浏览器解不了（WebP / AVIF）→ 包成 <picture>：能解 WebP 的
   浏览器看原图，解不了（IE 全系）的落到 JPEG 兜底（见 legacy/images.py）；
4. 连兜底也做不了（SVG / HEIC）→ 换成文字说明，否则页面上是破图标。

**图必须按属性解析，不能拿正则改字符串。** 早先的实现用 `<img\\b[^>]*>` 找
标签、再用正则找「第一个 src=」改写，两处都错（2026-11 审计）：

* 属性值里的 `>` 会让 `[^>]*` 提前收尾：`<img alt="x>y" src="…">` 被当成
  不完整标签，整段原样透出，跨域图反而没被换成占位；
* `title` / `alt` 里出现 `src=` 时，改写点落在别人的属性值中间，拼进去的
  裸引号把外层属性截断，`onerror` 从字符串变成真事件属性（存储型 XSS）。

html5lib / tinyhtml5 都不在依赖里（bleach 6.4 不要求它们，生产环境也没装），
所以这里用标准库 html.parser 解析属性、按「属性 → 转义 → 拼回」重写；
标签边界由解析器的词法给出（它按引号正确找 `>`），不再由正则猜。
其余字节（bleach 已清洗过的段落、链接）一个都不动，改动面只有 <img> 本身。
"""

import hashlib
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import bleach
from django.core.cache import cache

from .images import UNSUPPORTED_EXTS, fallback_url, source_type

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

#: <img> 上会保留的属性。bleach 已经按 ALLOWED_ATTRS 过滤过一遍，这里再列一次
#: 是为了「改写时只拼回白名单里的名字」——多一层也不花什么钱。
IMAGE_ATTRS = frozenset(ALLOWED_ATTRS["img"])

# IE8 及更早版本解不了的图片格式：遇到这类同源图先试 JPEG 兜底。
UNSUPPORTED_IMAGE_EXTS = UNSUPPORTED_EXTS
# 正文硬上限：清洗是纯 CPU 的，含表格/列表的真实排版超过线性
# （实测 256KB 0.5s、512KB 1.8s、1MB 8s）。生产默认单 worker，
# 一篇超长稿件的读者一多就能把整站拖死，所以在入口截断。
# 线上现存最长正文约 3KB，256KB 足够覆盖正常的长文与 Word 粘贴。
MAX_HTML_CHARS = 256 * 1024

# 清洗结果缓存：同一篇正文每个请求都要重跑一遍 bleach + 属性改写，
# 而它是纯函数（正文 + 本站主机名 → HTML），结果按内容哈希复用。
# 只缓存 4KB 以上的正文——小块内容重算比查缓存还便宜。
CACHE_MIN_CHARS = 4096
CACHE_SECONDS = 7 * 24 * 3600
# 清洗逻辑一改就得让旧缓存失效，动逻辑时把这个 tag 一起改。
CACHE_TAG = "legacy-render-1"

# 超限截断的占位说明：静态文字，不经过任何解析。
_TRUNCATED_NOTE = '<p class="legacy-truncated">（正文过长，只显示前一部分）</p>'

# script / style / iframe 等整块删除：bleach 的 strip=True 只剥标签、保留文字，
# 脚本源码会被当成正文显示出来。
#
# 这里用「找开始标签 → 找对应的结束标签」的线性扫描，不用 `<(script).*?</\1>`
# 那种正则：正文里堆 N 个未闭合的开始标签时，正则每失败一次就扫到文末，
# 复杂度 O(N x 文长)（实测 275KB 要 21 秒，等于让一个匿名读者把单 worker 占住）。
_BLOCK_TAGS = (
    "script", "style", "iframe", "object", "embed",
    "video", "audio", "canvas", "svg", "noscript",
)
_BLOCK_START_RE = re.compile(
    r"<(" + "|".join(_BLOCK_TAGS) + r")\b",
    re.I,
)
_BLOCK_CLOSE_RES = {}


def _block_close_re(name):
    """</name ...> 的匹配器；按名字缓存，避免每个标签都重新编译。"""
    pattern = _BLOCK_CLOSE_RES.get(name)
    if pattern is None:
        pattern = re.compile(r"</%s\s*>" % name, re.I)
        _BLOCK_CLOSE_RES[name] = pattern
    return pattern


def _strip_blocks(text):
    """整块删掉 script/style/iframe 等；没闭合的开始标签只丢标签本身。"""
    out = []
    pos = 0
    while True:
        match = _BLOCK_START_RE.search(text, pos)
        if match is None:
            break
        out.append(text[pos:match.start()])
        closer = _block_close_re(match.group(1).lower()).search(text, match.end())
        if closer is None:
            # 没闭合：只丢掉这个开始标签，后面的文字让 bleach 去剥。
            pos = match.end()
        else:
            pos = closer.end()
    out.append(text[pos:])
    return "".join(out)


def _strip_comments(text):
    """线性删掉 <!-- -->；未闭合的注释直接丢弃到文末（宁可少显示）。"""
    out = []
    pos = 0
    while True:
        start = text.find("<!--", pos)
        if start < 0:
            break
        out.append(text[pos:start])
        end = text.find("-->", start + 4)
        pos = len(text) if end < 0 else end + 3
    out.append(text[pos:])
    return "".join(out)


_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)

#: 出现在 URL 里就一票否决的字符：引号与尖括号本身是「属性已经破了」的信号；
#: 反斜杠会被旧浏览器当成 /（'/\\evil.example/x.png' → '//evil.example/x.png'）；
#: 控制字符会被 urlsplit 悄悄吃掉，凭空造出协议相对地址。
_UNSAFE_CHARS = frozenset("\"'<>\\`")


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


def _unsafe_url(value):
    """这个值不适合塞进 src/href：见 _UNSAFE_CHARS 上面的说明。"""
    for ch in value:
        if ch in _UNSAFE_CHARS or ord(ch) < 32 or ord(ch) == 127:
            return True
    return False


def _path_of(parts):
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if parts.query:
        path += "?" + parts.query
    return path


def _safe_path(path):
    """归一化之后的最后一道闸：必须是单个 / 开头的干净路径。

    绝对地址走 urlsplit 之后要重新过一遍：协议相对（//host/x）与反斜杠
    （/\\host/x）这两种写法在浏览器里都等于「去别的站取图」。
    """
    if not path or not path.startswith("/") or path.startswith("//"):
        return None
    if _unsafe_url(path):
        return None
    return path


def _same_origin_path(src, own_hosts):
    """返回站内路径；跨域或危险协议返回 None。

    主站编辑在正文里插图常常写成 http://<本站域名或 IP>/media/… 这样的
    绝对地址，浏览器打开时与相对地址等效。早先只认以 / 开头的写法，
    结果自己的图被当成外链拦掉（用户报的「外链图片未自动加载：8.153.145.175」），
    所以这里按主机名比对，同源就改写成路径。

    **先验原始值、再验归一化结果**：`http://<本站>/\\x.png` 与
    `http://<本站>/\\tx.png` 的 netloc 都是本站，但拼出来的路径会被浏览器
    解释成外站地址，只看 netloc 就漏了。
    """
    value = (src or "").strip()
    if not value or _unsafe_url(value):
        return None
    if value.startswith("//"):
        parts = urlsplit("http:" + value)
        if bare_host(parts.netloc) not in own_hosts:
            return None
        return _safe_path(_path_of(parts))
    if _SCHEME_RE.match(value):
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https"):
            return None
        if bare_host(parts.netloc) not in own_hosts:
            return None
        return _safe_path(_path_of(parts))
    if value.startswith("/"):
        return _safe_path(value)
    return None


def _host_of(src):
    try:
        parts = urlsplit(src)
    except ValueError:
        return ""
    return bare_host(parts.netloc) or (parts.path or "")


def _attr(value):
    """写回属性值：解析器已经把实体还原成字符了，这里只做一次转义。"""
    return escape(value, quote=True)


def _tag(name, attrs):
    parts = ["<", name]
    for key, value in attrs:
        parts.append(' %s="%s"' % (key, _attr(value)))
    parts.append(">")
    return "".join(parts)


def _external_placeholder(src):
    unsafe = _unsafe_url(src)
    host = "无法识别的地址" if unsafe else (_host_of(src) or "外部站点")
    link = ""
    if not unsafe:
        link = (
            '<br><a href="' + _attr(src) + '" target="_blank" rel="nofollow noopener noreferrer">'
            "在新窗口查看（可能向该站暴露你的 IP 与访问时间）</a>"
        )
    return '<div class="legacy-extimg">外链图片未自动加载：' + escape(host) + link + "</div>"


def _picture_with_fallback(path, attrs, fallback):
    """同源 WebP：原图放 <source>，JPEG 兜底放 <img>。

    现代浏览器挑 <source>，看到的是原图；IE 全系不认 <picture>/<source>，
    只渲染里面的 <img>，看到兜底图。不判 UA，也就不会让同一 URL 出现
    两份内容（缓存、Vary 都不用管）。
    """
    inner = [("src", fallback)] + [
        (name, value) for name, value in attrs if name != "src"
    ]
    return (
        '<picture><source type="%s" srcset="%s">%s</picture>'
        % (_attr(source_type(path)), _attr(path), _tag("img", inner))
    )


def _format_placeholder(path):
    name = path.split("?", 1)[0]
    ext = name.rsplit(".", 1)[-1].upper() if "." in name else ""
    link = ""
    if not _unsafe_url(path):
        link = (
            '<br><a href="' + _attr(path) + '" target="_blank" rel="nofollow noopener noreferrer">'
            "在新窗口打开原图（可以另存后用看图软件查看）</a>"
        )
    return (
        '<div class="legacy-extimg">'
        "这张图片是 " + escape(ext or "新") + " 格式，旧版浏览器无法直接显示。" + link + "</div>"
    )


def _is_unsupported(path):
    name = path.split("?", 1)[0].lower()
    return name.endswith(UNSUPPORTED_IMAGE_EXTS)


class _ImageRewriter(HTMLParser):
    """找出所有 <img>，用解析出的属性生成替换文本；其它字节原样保留。

    只记「替换区间」而不是重建整篇文档：bleach 的输出已经清洗过，没必要
    再经历一次序列化（那会把 &nbsp; 之类的实体改成裸字符，凭空扩大 diff）。
    """

    def __init__(self, text, hosts):
        HTMLParser.__init__(self, convert_charrefs=True)
        self._text = text
        self._hosts = hosts
        self._line_starts = [0]
        for match in re.finditer("\n", text):
            self._line_starts.append(match.end())
        self.edits = []
        self.external = 0
        self.unsupported = 0

    def _offset(self):
        line, column = self.getpos()
        index = line - 1
        if index < 0 or index >= len(self._line_starts):
            return None
        return self._line_starts[index] + column

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self._rewrite(attrs)

    def handle_startendtag(self, tag, attrs):
        if tag == "img":
            self._rewrite(attrs)

    def _rewrite(self, attrs):
        raw = self.get_starttag_text()
        start = self._offset()
        if not raw or start is None:
            return
        if self._text[start:start + len(raw)] != raw:
            # 行/列换算与解析器对不上时宁可不动：改错位置比少改一张图危险得多。
            return
        replacement = self._replacement(attrs)
        if replacement is not None:
            self.edits.append((start, start + len(raw), replacement))

    def _replacement(self, attrs):
        kept = []
        seen = set()
        for name, value in attrs:
            key = (name or "").lower()
            if key not in IMAGE_ATTRS or key in seen:
                continue
            seen.add(key)
            kept.append((key, value or ""))
        src = ""
        for name, value in kept:
            if name == "src":
                src = value.strip()
                break
        if not src:
            return None
        path = _same_origin_path(src, self._hosts)
        if path is None:
            self.external += 1
            return _external_placeholder(src)
        if _is_unsupported(path):
            fallback = fallback_url(path)
            if fallback:
                return _picture_with_fallback(path, kept, fallback)
            self.unsupported += 1
            return _format_placeholder(path)
        if path == src:
            return None
        # 同源绝对地址 → 相对路径：少一次 DNS，也不会把主机名写进页面。
        return _tag("img", [(name, path if name == "src" else value) for name, value in kept])


def _rewrite_images(cleaned, hosts):
    rewriter = _ImageRewriter(cleaned, hosts)
    try:
        rewriter.feed(cleaned)
        rewriter.close()
    except Exception:  # noqa: BLE001 - 解析器不该抛，抛了也绝不能把原图放出去
        return re.sub(r"<img\b[^>]*>", "", cleaned), 0, 0
    text = cleaned
    for start, end, replacement in sorted(rewriter.edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, rewriter.external, rewriter.unsupported


def _clip(text):
    """超过 MAX_HTML_CHARS 就在标签边界截断，返回 (截断后的文本, 是否截断)。"""
    if len(text) <= MAX_HTML_CHARS:
        return text, False
    cut = text.rfind("<", 0, MAX_HTML_CHARS)
    if cut <= 0:
        cut = MAX_HTML_CHARS
    return text[:cut], True


def _cache_key(text, hosts):
    digest = hashlib.sha1(CACHE_TAG.encode("ascii"))
    for host in sorted(hosts):
        digest.update(b"\x1f")
        digest.update(host.encode("utf-8", "replace"))
    digest.update(b"\x1e")
    digest.update(text.encode("utf-8", "replace"))
    return "legacy:render:" + digest.hexdigest()


def _cached(key):
    try:
        return cache.get(key)
    except Exception:  # noqa: BLE001 - 缓存坏了最多是重算，不能把页面打 500
        return None


def _store(key, value):
    try:
        cache.set(key, value, CACHE_SECONDS)
    except Exception:  # noqa: BLE001
        pass


def sanitize_legacy_html(html, own_hosts=()):
    """清洗正文，返回 (安全 HTML, 跨域图片张数, 格式不支持张数)。

    own_hosts 是本机认可的主机名集合（见 views._own_hosts），
    用来判断「本站的绝对地址」不是外链。
    """
    if not html:
        return "", 0, 0
    hosts = frozenset(bare_host(h) for h in own_hosts if h)
    text, truncated = _clip(html)
    key = None
    if len(text) >= CACHE_MIN_CHARS:
        key = _cache_key(text, hosts)
        hit = _cached(key)
        if hit is not None:
            out, external, unsupported = hit
            if truncated:
                out = out + _TRUNCATED_NOTE
            return out, external, unsupported
    text = _strip_comments(text)
    text = _strip_blocks(text)
    cleaned = bleach.clean(
        text,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    out, external, unsupported = _rewrite_images(cleaned, hosts)
    if key is not None:
        _store(key, (out, external, unsupported))
    if truncated:
        out = out + _TRUNCATED_NOTE
    return out, external, unsupported
