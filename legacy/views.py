"""旧浏览器只读版（/legacy/）的视图。

硬约束：
- 只读：只接受 GET / HEAD，其余一律 405；
- 无状态：不读 session、不写 Cookie，也不用 render(request, ...)——
  那会跑一遍 context processors（其中就有 auth / messages），
  轻则多查库，重则给访客种下 session。
- 独立响应头：CSP 默认全禁，只放行同源样式与图片。
"""

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods

from about.models import AboutBlock, AboutPage

from .queries import latest_news
from .sanitize import sanitize_legacy_html

LEGACY_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _render(template_name, context, status=200):
    body = render_to_string(template_name, context)
    response = HttpResponse(
        body, content_type="text/html; charset=utf-8", status=status,
    )
    response["Content-Security-Policy"] = LEGACY_CSP
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["X-Frame-Options"] = "DENY"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    # 允许反代短缓存；内容层是活的，60 秒足够削峰又不至于让撤稿停留太久。
    response["Cache-Control"] = "public, max-age=60"
    return response


@require_http_methods(["GET", "HEAD"])
def home(request):
    page = AboutPage.objects.first()
    intro_html, _ = sanitize_legacy_html(page.intro if page else "")
    return _render("legacy/home.html", {
        "page": page,
        "intro_html": intro_html,
        "news": latest_news(limit=5),
    })


@require_http_methods(["GET", "HEAD"])
def about(request):
    page = AboutPage.objects.first()
    intro_html, _ = sanitize_legacy_html(page.intro if page else "")
    blocks = []
    external_total = 0
    for block in AboutBlock.objects.all():
        html, external = sanitize_legacy_html(block.content)
        external_total += external
        blocks.append({"title": block.title, "html": html})
    return _render("legacy/about.html", {
        "page": page,
        "intro_html": intro_html,
        "blocks": blocks,
        "external_total": external_total,
    })
