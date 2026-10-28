"""首页「社团动态」聚合：新闻 / 活动 / 任务(登录可见) → 统一 feed。

可见性在服务端强制：任务仅登录用户可见；活动仅投影公开字段。
排序：已结束（closed / archived）的活动整体沉底，其余按 timestamp 降序，
同一优先级内按发布时间（活动=created_at）倒序；再类型打散（避免连续 3 同类），截断到 limit。
"""
from django.utils import timezone

from activities.lifecycle import ARCHIVED, CLOSED
from activities.models import Activity
from reviews.visibility import public_q
from tasks.models import Task

from .models import News

# 「已结束」的活动状态：这两类在 feed 里整体排到最后（仍在进行 / 待开始的排前面）。
_ENDED_ACTIVITY_STATUSES = frozenset({CLOSED, ARCHIVED})

# 任务「活跃」子集：未完结、未取消
_ACTIVE_TASK_STATUSES = ("pending", "in_progress", "reviewing", "review")


def _abs_url(request, value):
    """文件字段 → 绝对 URL（与 news.serializers._absolute_cover_url 行为一致）。"""
    if not value or not hasattr(value, "url"):
        return None
    url = value.url
    return request.build_absolute_uri(url) if request else url


def _news_dict(news, request):
    return {
        "type": "news",
        "id": news.pk,
        "title": news.title,
        "timestamp": (news.published_at or news.created_at).isoformat(),
        "summary": news.summary,
        "cover_image_url": _abs_url(request, news.cover_image),
        "cover_thumbnail_url": _abs_url(request, news.cover_thumbnail) or _abs_url(request, news.cover_image),
        "views": news.views,
    }


def _activity_dict(activity, request):
    """活动的公开投影：仅暴露卡片所需字段。活动已迁移至 activities app（ADR 0007）。"""
    return {
        "type": "activity",
        "id": activity.pk,
        "title": activity.title,
        "timestamp": activity.created_at.isoformat(),
        "activity_type": activity.type,  # deliberation / collection / exhibition
        "status": activity.status,
    }


def _assignee_dict(user):
    if user is None:
        return None
    profile = getattr(user, "profile", None)  # Profile 非自动创建；无则降级（与 tasks.SimpleUserSerializer 一致）
    return {
        "id": user.pk,
        "username": user.username,
        "nickname": getattr(profile, "nickname", "") or "",
        "avatar": (profile.avatar.url if profile and profile.avatar else None),
    }


def _task_dict(task, request):
    return {
        "type": "task",
        "id": task.pk,
        "title": task.title,
        "timestamp": (task.updated_at or task.created_at).isoformat(),
        "status": task.status,
        "priority": task.priority,
        "assignee": _assignee_dict(task.assignee),
    }


def _diversify(items):
    """轻量类型打散：若第 i 条与前两条同类型，则与后续最近的异类型交换（O(n)）。"""
    result = list(items)
    n = len(result)
    for i in range(2, n):
        t = result[i]["type"]
        if result[i - 1]["type"] == t and result[i - 2]["type"] == t:
            for j in range(i + 1, n):
                if result[j]["type"] != t:
                    result[i], result[j] = result[j], result[i]
                    break
    return result


def build_feed(*, request, limit=6):
    """聚合首页动态：``{"featured": <news>|None, "items": [<FeedItem>, ...]}``。

    - featured：头条新闻——**只有手工置顶（featured=True）才算头条**；没有置顶就是 None
      （不再退化为「阅读人数最高」，否则普通新闻会被误标成头条），且不计入 items。
    - items：活动 / 新闻 /（登录时的）任务。已结束的活动整体沉底，其余按 timestamp 降序，
      同一优先级内按发布时间倒序；再按类型打散，截断到 limit。
    - 可见性：任务仅登录用户可见；访客不可见仅成员调研；活动仅公开投影。
    """
    user = getattr(request, "user", None)
    is_authed = bool(user and user.is_authenticated)
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 6

    published = News.objects.filter(public_q("news"), is_published=True)
    featured_obj = published.filter(featured=True).order_by("-published_at", "-created_at").first()

    candidates = []  # [(priority, timestamp, dict), ...] —— priority 越小越靠前

    news_qs = published.exclude(pk=featured_obj.pk) if featured_obj else published
    for n in news_qs:
        candidates.append((0, (n.published_at or n.created_at), _news_dict(n, request)))

    activities = Activity.objects.filter(public_q("activity")).exclude(status=ARCHIVED)
    if not is_authed:
        # 访客不可见仅成员调研；众议/征集/展示标题泄漏保持原样
        activities = activities.exclude(type="survey", audience="members")
    for a in activities:
        rank = 1 if a.status in _ENDED_ACTIVITY_STATUSES else 0
        candidates.append((rank, a.created_at, _activity_dict(a, request)))

    if is_authed:
        tasks_qs = Task.objects.select_related("assignee", "assignee__profile").filter(
            status__in=_ACTIVE_TASK_STATUSES
        )
        for t in tasks_qs:
            candidates.append((0, (t.updated_at or t.created_at), _task_dict(t, request)))

    # 先按发布时间倒序，再按优先级稳定排序（priority 小=靠前；同级内保持时间倒序）
    candidates.sort(key=lambda triple: triple[1], reverse=True)
    candidates.sort(key=lambda triple: triple[0])
    # 打散只在同一优先级内进行：否则「连续 3 条新闻」的交换会把已结束活动拉回前排。
    active = [d for rank, _, d in candidates if rank == 0]
    ended = [d for rank, _, d in candidates if rank != 0]
    items = (_diversify(active) + _diversify(ended))[:limit]

    return {
        "featured": _news_dict(featured_obj, request) if featured_obj else None,
        "items": items,
    }
