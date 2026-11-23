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
    _file_url,
    activities_page,
    activity_card,
    author_name,
    cover_url,
    exhibit_cards,
    featured_news,
    get_activity,
    get_news,
    get_tutorial,
    hot_news,
    human_size,
    latest_activities,
    latest_news,
    news_card,
    news_page,
    news_tags,
    related_activities,
    related_news,
    tutorial_card,
    tutorials_page,
    vote_options,
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
        "activities": [activity_card(a) for a in latest_activities(limit=3)],
    })


def _about_document(block):
    """关于区块的附件：只给同源下载链接，不做内嵌预览（IE8 没有 PDF 阅读器）。"""
    field = block.document
    if not field:
        return None
    url = _file_url(field)
    if not url:
        return None
    try:
        size = field.size
    except (OSError, ValueError):
        size = 0
    return {
        "url": url,
        "name": field.name.rsplit("/", 1)[-1] or "附件",
        "size": human_size(size),
    }


@require_http_methods(["GET", "HEAD"])
def about(request):
    page = AboutPage.objects.first()
    intro_html, _ = sanitize_legacy_html(page.intro if page else "")
    blocks = []
    external_total = 0
    for block in AboutBlock.objects.all():
        # 校园全景靠 WebGL（Marzipano）渲染，旧浏览器无解：整块不输出正文，
        # 只在原位置换成一句可读说明，避免“标题下面一块空白”。
        is_panorama = block.key == "campus-overview"
        if is_panorama:
            html = ""
        else:
            html, external = sanitize_legacy_html(block.content)
            external_total += external
        blocks.append({
            "key": block.key,
            "title": block.title,
            "html": html,
            "is_panorama": is_panorama,
            "doc": _about_document(block),
        })
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


@require_http_methods(["GET", "HEAD"])
def activities_list(request):
    type_key = (request.GET.get("type") or "").strip()
    page = activities_page(request.GET.get("page", 1), type_filter=type_key)
    return _render("legacy/activities_list.html", {
        "page": page,
        "items": [activity_card(a) for a in page.object_list],
        "type_key": type_key,
        "type_tabs": [
            {"key": "deliberation", "label": "众议"},
            {"key": "exhibition", "label": "展示"},
            {"key": "survey", "label": "调研"},
        ],
    })


@require_http_methods(["GET", "HEAD"])
def activity_detail(request, pk):
    activity = get_activity(pk)
    if activity is None:
        return _render("legacy/missing.html", {
            "what": "这个活动不存在，或没有对游客公开。",
        }, status=404)
    body_html, external_total = sanitize_legacy_html(activity.body)
    options = vote_options(activity) if activity.type == "deliberation" else []
    exhibits = exhibit_cards(activity) if activity.type == "exhibition" else []
    return _render("legacy/activity_detail.html", {
        "card": activity_card(activity),
        "body_html": body_html,
        "external_total": external_total,
        "options": options,
        "exhibits": exhibits,
        "related": [activity_card(a) for a in related_activities(activity)],
    })


@require_http_methods(["GET", "HEAD"])
def tutorials_list(request):
    page = tutorials_page(request.GET.get("page", 1))
    return _render("legacy/tutorials_list.html", {
        "page": page,
        "items": [tutorial_card(t) for t in page.object_list],
    })


@require_http_methods(["GET", "HEAD"])
def tutorial_detail(request, pk):
    tutorial = get_tutorial(pk)
    if tutorial is None:
        return _render("legacy/missing.html", {
            "what": "这个教程不存在，或尚未公开。",
        }, status=404)
    return _render("legacy/tutorial_detail.html", {
        "card": tutorial_card(tutorial),
    })
