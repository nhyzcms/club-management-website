"""只读查询层。

legacy 不复制数据、不建缓存表：每个请求都直接查主站同一个数据库，
并把「什么算公开」交给主站同一段代码判定（reviews.visibility.public_q）。
结构层（模板 / CSS / 路由）才需要发版，内容层永远是活的。
"""

from django.core.paginator import Paginator
from django.db.models import Count, Q

from common.models import Tag
from news.models import News
from reviews.visibility import public_q

# 保守分页：旧浏览器一次请求过多条目容易超时，也给数据库留余量。
NEWS_PAGE_SIZE = 20
# 深分页上限：爬虫顺着 ?page= 往上加时不要把数据库拖死。
MAX_PAGE = 200


def public_news():
    """主站公开新闻：已发布 且 审核已通过（与 news/views.py 的匿名口径一致）。"""
    return (
        News.objects.filter(is_published=True)
        .filter(public_q("news"))
        .order_by("-published_at", "-created_at")
    )


def latest_news(limit=5):
    return list(public_news()[:limit])


def featured_news():
    """头条只认手工置顶（featured=True），与主站 /news/news/featured/ 同口径。"""
    return public_news().filter(featured=True).first()


def hot_news(limit=5):
    """热门阅读：按阅读人数，与主站 /news/news/hot/ 同口径。"""
    return list(public_news().order_by("-views", "-published_at")[:limit])


def news_tags(limit=20):
    """标签云：只统计公开新闻，计数也只算公开稿。"""
    return list(
        Tag.objects.filter(news__in=public_news())
        .annotate(cnt=Count("news", filter=Q(news__is_published=True) & public_q("news")))
        .filter(cnt__gt=0)
        .order_by("-cnt", "name")[:limit]
    )


def search_news(keyword="", qs=None):
    """关键词搜索：字段与主站 DRF SearchFilter 一致（标题 / 摘要 / 正文）。"""
    base = public_news() if qs is None else qs
    word = (keyword or "").strip()[:80]
    if not word:
        return base
    return base.filter(
        Q(title__icontains=word)
        | Q(summary__icontains=word)
        | Q(content__icontains=word)
    )


def news_page(number=1, keyword=""):
    """分页对象。页码越界交给 Paginator 收敛，非法值退回第 1 页。"""
    try:
        wanted = int(number)
    except (TypeError, ValueError):
        wanted = 1
    wanted = min(max(wanted, 1), MAX_PAGE)
    paginator = Paginator(search_news(keyword), NEWS_PAGE_SIZE)
    return paginator.get_page(wanted)


def get_news(pk):
    """单篇公开新闻；不存在 / 未发布 / 未过审一律 None（交给视图回 404）。"""
    return (
        public_news()
        .select_related("author", "author__profile")
        .prefetch_related("tags")
        .filter(pk=pk)
        .first()
    )


def related_news(news, limit=3):
    """相关阅读：主站同口径——最新公开稿，排除自身。"""
    return list(
        public_news()
        .exclude(pk=news.pk)
        .select_related("author", "author__profile")
        .prefetch_related("tags")[:limit]
    )


def author_name(news):
    """作者显示名：昵称优先，退回用户名；不查额外表（profile 已 select_related）。"""
    profile = getattr(news.author, "profile", None)
    nickname = getattr(profile, "nickname", "") or ""
    return nickname.strip() or news.author.get_username()


def cover_url(news):
    """封面：缩略图优先，退回原图；都没有返回空串。"""
    for field in ("cover_thumbnail", "cover_image"):
        image = getattr(news, field, None)
        if image:
            try:
                return image.url
            except ValueError:
                continue
    return ""


def news_card(news):
    """模板用的轻量结构（避免模板里做逻辑，也让序列化口径集中在一处）。"""
    return {
        "id": news.pk,
        "title": news.title,
        "summary": news.summary,
        "date": news.published_at or news.created_at,
        "views": news.views,
        "thumb": cover_url(news),
        "author": author_name(news),
        "featured": news.featured,
    }