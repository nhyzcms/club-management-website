"""共享富文本 HTML 净化器。

服务端清洗可挡住成员绕过编辑器、直接经 API 注入的 <script> / 事件处理器 / javascript: 等。
被 news（新闻正文）与 about（关于页正文）共用——白名单与前端 RichTextEditor
（TipTap：StarterKit + TaskList + Table + Image + Video + Iframe + Underline /
Highlight / TextAlign / Color 等）输出对齐。

行内样式闸门（2026-09-26 起）：编辑器「对齐 / 文字颜色 / 高亮」会输出 style 属性。
仅对 p / h1-h6 / span / mark 放行 style（mark 即高亮，只需背景色），且经 _StyleSanitizer
（bleach css_sanitizer 接口）只保留 text-align / color / background-color 三种属性 +
受限值格式（hex / rgb(a)）；url()、expression、定位类属性等一律剥除。
"""
import bleach
import re
import urllib.parse

from django.conf import settings

# 正文 HTML 白名单
_ALLOWED_TAGS = [
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "s", "del", "u", "mark", "code", "sub", "sup",
    "pre", "blockquote",
    "ul", "ol", "li",
    "a", "img", "iframe", "video",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "figure", "figcaption", "span",
]

# iframe 策略（2026-08-04 起）：允许任意 https iframe（不再做平台域白名单）——编辑者
# （信息组 / about 编辑）为受信角色。补偿控制：
#   - src 仅放行 https 或协议相对 //host（//host 在 https 站点即 https，常见 embed 惯例）；
#     http / 相对路径 / javascript: 一律剥，剥后空壳 iframe 由正则清除；
#   - srcdoc 一律剥（防内嵌任意 HTML/JS，即便带 https src 作掩护）；
#   - 用户给的 sandbox 与 allow（Permissions-Policy）一律作废，由服务端统一盖戳（见
#     _IFRAME_SANDBOX / _IFRAME_ALLOW）——sandbox 故意不给 allow-top-navigation（防 top-nav
#     重定向钓鱼），allow 仅放行播放所需（不放 camera/mic/geolocation/payment）；
#   - 事件处理器（onload 等）/ <script> 仍被 bleach 挡。
# 残面：视觉钓鱼（假登录框）不归代码管，靠角色信任兜底。
#
# iframe 允许的属性（src 单独判 https；srcdoc / sandbox / allow / on* 均不在此 → 被剥，由服务端统一盖戳）。
_IFRAME_SAFE_ATTRS = frozenset({"frameborder", "width", "height", "loading", "title"})
# 服务端强制盖戳的 sandbox 值：跨源 embed 所需最小集；不含 allow-top-navigation（防 top-nav 钓鱼）。
_IFRAME_SANDBOX = "allow-scripts allow-same-origin allow-popups allow-presentation"
# 服务端强制盖戳的 allow（Permissions-Policy）值：仅播放所需，不放 camera/mic/geolocation/payment。
_IFRAME_ALLOW = "autoplay; fullscreen; picture-in-picture"


def _is_site_host(host: str) -> bool:
    """host 是否属于本站（``ALLOWED_HOSTS``）——用于拒绝**同源 iframe**。

    为什么必须拒同源：iframe 的 sandbox 同时给了 ``allow-scripts`` 与
    ``allow-same-origin``，对**同源**文档而言这等于没有沙箱——iframe 内的脚本
    可以直接读写父页面、发同源请求、读 ``csrftoken``。攻击者只要能让一段 HTML
    落在本站同源（上传、遗留文件、其它漏检入口），再在正文里引用它，就能在
    「审核台预览 / 新闻详情 / 关于页」这些自动渲染的地方执行任意脚本
    （2026-10-31 审计 S-3 的攻击路径 A/B/C）。

    跨源 iframe 不受影响：浏览器同源策略本来就不让它读我们的 DOM，
    ``allow-same-origin`` 只是让它能访问**自己的** storage（B 站 / YouTube 播放器需要）。
    """
    host = (host or "").split(":")[0].strip().lower()
    if not host:
        return False
    for allowed in getattr(settings, "ALLOWED_HOSTS", None) or []:
        allowed = str(allowed).strip().lower()
        if not allowed or allowed == "*":
            continue
        if allowed.startswith("."):
            if host == allowed[1:] or host.endswith(allowed):
                return True
        elif host == allowed:
            return True
    return False


def _iframe_attr_filter(tag, name, value):
    """bleach 属性回调：iframe 的 src 仅放行 https 或协议相对 //host（后者在 https 站点即 https，
    是常见 embed 惯例，如网易云外链播放器）；http / 相对路径 / javascript: 一律剥，剥后空壳 iframe
    由 _IFRAME_WITHOUT_SRC_RE 清除。其余属性须在安全白名单内（srcdoc / sandbox / allow / onload 等
    不在内 → 剥离；sandbox 与 allow 由 _stamp_iframe_attrs 统一盖戳）。

    另：指向**本站域名**的 iframe 一律剥（见 ``_is_site_host`` 的说明）——同源 + 允许脚本
    = 等价于父页面内联脚本。"""
    if name == "src":
        try:
            parsed = urllib.parse.urlparse(value)
        except (ValueError, TypeError):
            return False
        if parsed.scheme == "https":
            # 同源 embed 等于把任意落盘 HTML 当脚本执行，直接拒
            return not _is_site_host(parsed.netloc)
        # 协议相对（//host）：scheme 空、netloc 非空 → 在 https 站点即 https
        if parsed.scheme == "" and parsed.netloc:
            return not _is_site_host(parsed.netloc)
        return False
    return name in _IFRAME_SAFE_ATTRS


# 清除 src 被剥（http / 非法 / 缺失）的空壳 iframe：bleach 仅剥属性留 <iframe></iframe> 空壳。
_IFRAME_WITHOUT_SRC_RE = re.compile(
    r"<iframe\b(?![^>]*\bsrc=)[^>]*>.*?</iframe>", re.IGNORECASE | re.DOTALL,
)
# 给（已被 bleach 剥掉用户 sandbox/allow 的）存活 iframe 统一注入 sandbox+allow 戳。仅匹配尚无 sandbox 者，幂等。
_IFRAME_STAMP_RE = re.compile(r"<iframe\b(?![^>]*\bsandbox=)", re.IGNORECASE)


def _stamp_iframe_attrs(html: str) -> str:
    """给每个存活 iframe 注入统一 sandbox + allow 戳（用户粘的 sandbox/allow 已被 _iframe_attr_filter 剥）。"""
    return _IFRAME_STAMP_RE.sub(
        f'<iframe sandbox="{_IFRAME_SANDBOX}" allow="{_IFRAME_ALLOW}"', html
    )


_ALLOWED_ATTRS = {
    "*": ["class"],
    # 行内样式：仅编辑器「对齐 / 文字颜色 / 高亮」输出所需标签（值经 _StyleSanitizer 过滤）
    "p": ["style"],
    "h1": ["style"],
    "h2": ["style"],
    "h3": ["style"],
    "h4": ["style"],
    "h5": ["style"],
    "h6": ["style"],
    "span": ["class", "style"],
    "mark": ["style"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "iframe": _iframe_attr_filter,
    "video": ["src", "controls", "preload", "width", "height", "poster"],
    "th": ["colspan", "rowspan", "colwidth"],
    "td": ["colspan", "rowspan", "colwidth"],
    "ul": ["class", "data-type"],
    "ol": ["class", "data-type"],
    "li": ["class", "data-type", "data-checked"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]

# ---- 行内样式白名单（见模块 docstring）----
# 值格式：hex 色 / rgb(a)（字符集受限，杜绝 url()、表达式、注入）；text-align 仅四方位。
_COLOR_VALUE_RE = re.compile(
    r"\A(?:#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})"
    r"|rgba?\([\d\s.,%]{1,64}\))\Z"
)
_STYLE_PROPS = {
    "text-align": re.compile(r"\A(?:left|right|center|justify)\Z"),
    "color": _COLOR_VALUE_RE,
    "background-color": _COLOR_VALUE_RE,
}


class _StyleSanitizer:
    """bleach css_sanitizer 接口：清洗 style 属性值——仅白名单属性 + 受限值格式。"""

    def sanitize_css(self, css: str) -> str:
        kept = []
        for decl in (css or "").split(";"):
            prop, sep, val = decl.partition(":")
            if not sep:
                continue
            prop = prop.strip().lower()
            val = val.strip()
            pattern = _STYLE_PROPS.get(prop)
            if pattern and pattern.match(val):
                kept.append(f"{prop}: {val}")
        return "; ".join(kept)


_STYLE_SANITIZER = _StyleSanitizer()
# 清洗后残留的空 style（值被整体剥除）：连属性一起去掉，避免输出 style=""。
_EMPTY_STYLE_RE = re.compile(r"\sstyle=(?:\"\"|'')")


def sanitize_html(html: str) -> str:
    """清洗正文 HTML：仅保留白名单标签/属性/协议，其余剥离（strip=True，内容保留）；
    iframe 仅放行 https src、剥 srcdoc/用户 sandbox/用户 allow，存活者统一盖 sandbox+allow 戳；
    style 仅 p / h1-h6 / span / mark 上放行，值经 _StyleSanitizer 只留 text-align / color / background-color。"""
    if not html:
        return html
    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        css_sanitizer=_STYLE_SANITIZER,  # pyright: ignore[reportArgumentType] —— 鸭子类型：只需 sanitize_css 方法（免 tinycss2 依赖）
    )
    cleaned = _IFRAME_WITHOUT_SRC_RE.sub("", cleaned)  # 清 http / 无 src 的空壳 iframe
    cleaned = _EMPTY_STYLE_RE.sub("", cleaned)  # 清值被剥除后残留的空 style
    return _stamp_iframe_attrs(cleaned)
