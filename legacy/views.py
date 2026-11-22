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

from .queries import (
    author_name,
    cover_url,
    featured_news,
    get_news,
    hot_news,
    latest_news,
    news_card,
    news_page,
    news_tags,
    related_news,
)
from .sanitize import sanitize_legacy_html

LEGACY_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
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
        "news": [news_card(n) for n in latest_news(limit=5)],
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


@require_http_methods(["GET", "HEAD"])
def news_list(request):
    keyword = request.GET.get("q", "")
    page = news_page(request.GET.get("page", 1), keyword=keyword)
    items = [news_card(n) for n in page.object_list]
    feature = None
    # 头条只在未筛选的第一页出现，且从列表里剔除，避免同一篇出现两次。
    if page.number == 1 and not keyword.strip():
        top = featured_news()
        if top is not None:
            feature = news_card(top)
            items = [i for i in items if i["id"] != feature["id"]]
    return _render("legacy/news_list.html", {
        "keyword": keyword.strip()[:80],
        "page": page,
        "items": items,
        "feature": feature,
        "hot": [news_card(n) for n in hot_news(limit=5)],
        "tags": news_tags(limit=20),
    })


@require_http_methods(["GET", "HEAD"])
def news_detail(request, pk):
    news = get_news(pk)
    if news is None:
        return _render("legacy/missing.html", {
            "what": "这篇新闻不存在，或尚未公开。",
        }, status=404)
    content_html, external_total = sanitize_legacy_html(news.content)
    return _render("legacy/news_detail.html", {
        "news": news,
        "card": news_card(news),
        "author": author_name(news),
        "cover": cover_url(news),
        "content_html": content_html,
        "external_total": external_total,
        "related": [news_card(n) for n in related_news(news)],
    })
