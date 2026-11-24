"""只读查询层。

legacy 不复制数据、不建缓存表：每个请求都直接查主站同一个数据库，
并把「什么算公开」交给主站同一段代码判定（reviews.visibility.public_q）。
结构层（模板 / CSS / 路由）才需要发版，内容层永远是活的。
"""

from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q

from activities.lifecycle import order_activities
from activities.models import Activity, Exhibit, VoteOption
from activities.state import calc_state
from attachments.models import Attachment
from news.models import News
from reviews.visibility import public_q
from tutorials.models import Tutorial

from .images import UNSUPPORTED_EXTS, fallback_url, needs_fallback, source_type

# 保守分页：旧浏览器一次请求过多条目容易超时，也给数据库留余量。
NEWS_PAGE_SIZE = 20
ACTIVITY_PAGE_SIZE = 20
TUTORIAL_PAGE_SIZE = 20
# 深分页上限：爬虫顺着 ?page= 往上加时不要把数据库拖死。
MAX_PAGE = 200

# IE8 及更早版本解不了的图片格式。这类图不直接给 <img>，而是用
# <picture>（能解的浏览器看原图，解不了的落到 JPEG 兜底），见 legacy/images.py。
UNSUPPORTED_IMAGE_EXTS = UNSUPPORTED_EXTS

# 匿名可见的活动类型：征集（collection）匿名永远看不到（见 activities/views.py:132），
# 所以 legacy 的类型筛选也只提供这三类。
PUBLIC_ACTIVITY_TYPES = ("deliberation", "exhibition", "survey")
_STATUS_LABELS = dict(Activity.STATUS_CHOICES)
_ENDED_STATES = frozenset({"closed", "archived"})


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
    """标签云：只统计公开新闻，计数也只算公开稿。

    必须从 News 侧聚合：public_q("news") 的形状是 Q(pk__in=…)，挂在 Tag 的
    queryset 上时 pk 会被解析成 Tag.pk，计数恒为 0——v1.2.0 起标签云一直是空的
    （审计 2026-11）。从 News 出发，pk 就是 News 的 pk，口径与列表页逐字一致：
    同一个 public_news()，同一次可见性判定，不另写一份「什么算公开」。
    """
    rows = (
        public_news()
        .order_by()
        .filter(tags__isnull=False)
        .values("tags__id", "tags__name")
        .annotate(cnt=Count("pk", distinct=True))
        .order_by("-cnt", "tags__name")[:limit]
    )
    return [
        {"id": row["tags__id"], "name": row["tags__name"], "cnt": row["cnt"]}
        for row in rows
    ]


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


def _page_number(number):
    """页码收敛：非法值退回第 1 页，超过 MAX_PAGE 截断，再交给 Paginator。"""
    try:
        wanted = int(number)
    except (TypeError, ValueError):
        wanted = 1
    return min(max(wanted, 1), MAX_PAGE)


def news_page(number=1, keyword=""):
    """分页对象。页码越界交给 Paginator 收敛，非法值退回第 1 页。"""
    paginator = Paginator(search_news(keyword), NEWS_PAGE_SIZE)
    return paginator.get_page(_page_number(number))


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


def image_box(field_file):
    """图片字段 → {"url", "fallback", "note"}。

    - url：站内原图地址（只认同源相对路径，CSP 只放行本站图片）；
    - fallback：原图是 WebP / AVIF 时，另生成的 JPEG 兜底图地址，
      模板用 <picture> 让现代浏览器看原图、旧浏览器看兜底；
    - note：两样都给不了时给旧浏览器看的一句话（例如 SVG）。

    不直接写死「WebP 一律不显示」：能显示 WebP 的浏览器（Chrome / Edge /
    Firefox / Safari 14+）不该被一起降级。
    """
    url = _file_url(field_file)
    if not url:
        return {"url": "", "fallback": "", "mime": "", "note": ""}
    if needs_fallback(url):
        fallback = fallback_url(url)
        if fallback:
            return {"url": url, "fallback": fallback, "mime": source_type(url), "note": ""}
        ext = url.split("?", 1)[0].rsplit(".", 1)[-1].upper()
        return {
            "url": "", "fallback": "", "mime": "",
            "note": "此图为 %s 格式，旧版浏览器无法直接显示" % ext,
        }
    return {"url": url, "fallback": "", "mime": source_type(url), "note": ""}


def cover_box(news):
    """封面：缩略图优先，退回原图；都没有返回空结构。"""
    for field in ("cover_thumbnail", "cover_image"):
        image = getattr(news, field, None)
        if image:
            box = image_box(image)
            if box["url"] or box["note"]:
                return box
    return {"url": "", "fallback": "", "mime": "", "note": ""}


def cover_url(news):
    """封面地址（旧浏览器能显示时才有值，其余情况返回空串）。"""
    return cover_box(news)["url"]


def news_card(news):
    """模板用的轻量结构（避免模板里做逻辑，也让序列化口径集中在一处）。"""
    box = cover_box(news)
    return {
        "id": news.pk,
        "title": news.title,
        "summary": news.summary,
        "date": news.published_at or news.created_at,
        "views": news.views,
        "thumb": box["url"],
        "thumb_fallback": box["fallback"],
        "thumb_mime": box["mime"],
        "thumb_note": box["note"],
        "author": author_name(news),
        "featured": news.featured,
    }

# ==================== 活动（activities） ====================


def public_activities():
    """匿名可看的活动：审核已通过 + 受众公开 + 限定类型。

    与主站 activities/views.py:132 的匿名口径等价（那边写的是
    `Q(type="survey", audience="public") | Q(type__in=("deliberation","exhibition"), audience="public")`）。
    受众默认是 members，所以这里**宁少不扩大**：只放 explicitly public 的活动。
    """
    return order_activities(
        Activity.objects.filter(public_q("activity"))
        .filter(audience="public", type__in=PUBLIC_ACTIVITY_TYPES)
        .select_related("creator", "creator__profile")
    )


def activity_card(activity):
    """模板用的活动摘要。状态取 calc_state（纯函数），不读落库快照。

    legacy 绝不写库：不调用 transition_due_starts / transition_overdue，
    所以库里 status 可能滞后；展示层用 calc_state 现算即可与主站一致。
    """
    state = calc_state(activity)
    return {
        "id": activity.pk,
        "title": activity.title,
        "type": activity.get_type_display(),
        "type_key": activity.type,
        "state": state,
        "state_label": _STATUS_LABELS.get(state, state),
        "ended": state in _ENDED_STATES,
        "audience": activity.get_audience_display(),
        "creator": display_name(activity.creator),
        "created": activity.created_at,
        "start": activity.start_at,
        "end": activity.end_at,
        "permanent": activity.is_permanent,
    }


def activities_page(number=1, type_filter=""):
    """活动列表分页。type_filter 只接受白名单里的类型，其它值当「全部」。"""
    qs = public_activities()
    if type_filter in PUBLIC_ACTIVITY_TYPES:
        qs = qs.filter(type=type_filter)
    return Paginator(qs, ACTIVITY_PAGE_SIZE).get_page(_page_number(number))


def latest_activities(limit=3):
    """首页「近期活动」：先列未结束的，已结束的沉底（与主站列表同一顺序）。"""
    return list(public_activities()[:limit])


def get_activity(pk):
    """单个公开活动；不存在 / 未过审 / 仅成员受众一律 None（交给视图回 404）。"""
    return (
        public_activities()
        .filter(pk=pk)
        .prefetch_related(
            Prefetch(
                "options",
                queryset=VoteOption.objects.annotate(votes=Count("selections")).order_by("order", "id"),
            ),
            Prefetch(
                "exhibits",
                queryset=Exhibit.objects.annotate(votes=Count("vote_option__selections")).order_by("created_at"),
            ),
        )
        .first()
    )


def vote_options(activity):
    """众议选项 + 票数 + 占比（只给聚合数字；秘密投票也只暴露聚合，与主站一致）。"""
    rows = [
        {"id": option.pk, "text": option.text, "votes": option.votes}
        for option in activity.options.all()
    ]
    total = sum(row["votes"] for row in rows)
    for row in rows:
        row["percent"] = int(row["votes"] * 100 / total) if total else 0
    return rows


def exhibit_cards(activity):
    """展示活动的展品 + 首张图片 + 票数。图片只取同源附件（外链一律不加载）。"""
    exhibits = list(activity.exhibits.all())
    if not exhibits:
        return []
    covers = {}
    ids = [exhibit.pk for exhibit in exhibits]
    rows = (
        Attachment.objects.filter(
            target__kind="exhibit", target__object_id__in=ids, file_type="image",
        )
        .select_related("target")
        .order_by("uploaded_at")
    )
    for attachment in rows:
        object_id = attachment.target.object_id if attachment.target else None
        if object_id is None or object_id in covers:
            continue
        covers[object_id] = image_box(attachment.file)
    return [
        {
            "id": exhibit.pk,
            "title": exhibit.title or "（未命名展品）",
            "cover": covers.get(exhibit.pk, {}).get("url", ""),
            "cover_fallback": covers.get(exhibit.pk, {}).get("fallback", ""),
            "cover_mime": covers.get(exhibit.pk, {}).get("mime", ""),
            "cover_note": covers.get(exhibit.pk, {}).get("note", ""),
            "votes": exhibit.votes,
        }
        for exhibit in exhibits
    ]


def related_activities(activity, limit=4):
    """其它活动：最新公开活动，排除自身。"""
    return list(public_activities().exclude(pk=activity.pk)[:limit])


# ==================== 教程（tutorials） ====================


def public_tutorials():
    """公开教程：审核已通过。匿名列表与主站 visible_queryset(..., "tutorial") 等价。"""
    return (
        Tutorial.objects.filter(public_q("tutorial"))
        .select_related("uploader", "uploader__profile")
        .annotate(favorite_count=Count("favorites", distinct=True))
        .order_by("-created_at")
    )


def tutorial_card(tutorial):
    box = image_box(tutorial.cover)
    return {
        "id": tutorial.pk,
        "title": tutorial.title,
        "desc": tutorial.description,
        "type": tutorial.get_file_type_display(),
        "type_key": tutorial.file_type,
        "cover": box["url"],
        "cover_fallback": box["fallback"],
        "cover_mime": box["mime"],
        "cover_note": box["note"],
        "views": tutorial.views,
        "favorites": tutorial.favorite_count,
        "uploader": display_name(tutorial.uploader),
        "date": tutorial.created_at,
        "file_url": _file_url(tutorial.file),
        "file_name": tutorial.file_name,
        "file_size": human_size(tutorial.file_size),
    }


def tutorials_page(number=1):
    return Paginator(public_tutorials(), TUTORIAL_PAGE_SIZE).get_page(_page_number(number))


def get_tutorial(pk):
    return public_tutorials().filter(pk=pk).first()


# ==================== 小工具 ====================


def display_name(user):
    """用户显示名：昵称优先，退回用户名；没有用户返回空串。"""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    nickname = (getattr(profile, "nickname", "") or "").strip()
    return nickname or user.get_username()


def _file_url(field_file):
    """FileField → 站内 URL；外链存储或缺失一律返回空串（CSP 只放行同源图片）。"""
    if not field_file:
        return ""
    try:
        url = field_file.url
    except (ValueError, AttributeError):
        return ""
    return url if isinstance(url, str) and url.startswith("/") else ""


def human_size(size):
    """字节数 → 可读字符串（模板里不做算术）。"""
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return "未知大小"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return "%d B" % value
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return ""
