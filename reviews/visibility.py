"""公开可见性：审核轴只门控「公开展示」，不改对象自身生命周期。

## B9 之后为什么这么写

`Review` 上原来的 `news` / `activity` / `tutorial` 三个外键删了，审核行只通过
`ContentTarget` 锚定宿主。这意味着**宿主侧没有指向 target 的外键**——不能写
`News.objects.filter(review__status=...)`，那条反向关系不存在了。

但方向反过来是通的：`ContentTarget` 上有 `review` 反向（`Review.target` 的
related_name），所以可以查 `ContentTarget.objects.filter(kind=..., review__status=...)`
拿到 `object_id` 集合，再用 `pk__in` 子查询回到宿主表。

## 语义必须逐条对齐

`public_q` 是「内容该不该公开」的判定，算错就是该藏的内容露出去。改动时和旧实现
一一对照：

| kind | 旧实现 | 新实现 |
|---|---|---|
| news | `Q(review__status=APPROVED)` | `Q(pk__in=已过审的 object_id)` |
| activity | `Q(publication_review__status=APPROVED)` 或 `Q(publication_review__isnull=True)` | `Q(pk__in=已过审)` 或 `~Q(pk__in=有审核行的)` |
| tutorial | `Q(review__status=APPROVED)` | `Q(pk__in=已过审的 object_id)` |

news / tutorial 是 INNER JOIN 语义：**没有审核行的对象不公开**。
activity 多一条 `isnull=True`：**没有审核行的活动公开**（存量 ORM 与测试夹具的例外）。

`~Q(pk__in=有审核行的)` 覆盖「连 target 都没有」的活动——它们不在集合里所以判真，
和旧的 `isnull=True` 一致。
"""
from django.db.models import Q

from common.models import ContentTarget

from .models import Review

_OWNER_ID_ATTR = {
    "news": "author_id",
    "activity": "creator_id",
    "tutorial": "uploader_id",
}
_OWNER_LOOKUP = {
    "news": "author",
    "activity": "creator",
    "tutorial": "uploader",
}


def owner_id(obj):
    """对象作者/发起人/上传者的 pk（新闻 author、活动 creator、教程 uploader）。"""
    attr = _OWNER_ID_ATTR.get(obj._meta.model_name)
    if attr is None:
        raise TypeError(f"{type(obj).__name__} 没有挂审核行")
    return getattr(obj, attr)


def _approved_object_ids(kind):
    """该类型下已过审的对象 pk 子查询。"""
    return ContentTarget.objects.filter(
        kind=kind, review__status=Review.STATUS_APPROVED,
    ).values("object_id")


def _with_review_object_ids(kind):
    """该类型下「有审核行」的对象 pk 子查询。"""
    return ContentTarget.objects.filter(
        kind=kind, review__isnull=False,
    ).values("object_id")


def public_q(kind):
    """公开读的审核轴 ``Q``（用在宿主表的 queryset 上）。"""
    if kind == "news":
        return Q(pk__in=_approved_object_ids("news"))
    if kind == "activity":
        return Q(pk__in=_approved_object_ids("activity")) | ~Q(
            pk__in=_with_review_object_ids("activity")
        )
    if kind == "tutorial":
        return Q(pk__in=_approved_object_ids("tutorial"))
    raise ValueError(f"未知审核类型: {kind!r}")


def _review_of(obj):
    """对象上的审核行；没有则 None。

    走 ``target__kind`` + ``target__object_id`` 等值条件，不建 target 行——
    这是读路径，不该有写副作用。
    """
    return Review.objects.filter(
        target__kind=obj._meta.model_name,
        target__object_id=obj.pk,
    ).first()


def status_of(obj):
    """读对象当前审核状态；尚无审核记录时返回 None。"""
    review = _review_of(obj)
    return review.status if review else None


def comment_for(obj, user):
    """审核评语：仅作者/持 moderate 者可见；其余（含公众）得到空串。"""
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    if user.pk != owner_id(obj) and not user.has_perm("reviews.moderate"):
        return ""
    review = _review_of(obj)
    return (review.moderation_note or "") if review else ""


def visible_queryset(qs, user, kind, *, action):
    """审核轴可见性：公开列表 vs 作者预览 vs ``reviews.moderate`` 全量。

    - ``action == "retrieve"``：持 moderate 看全部；作者看自己的；其余只看 ``public_q``。
    - 其它 action：仅 ``public_q``（公开列表）。
    ``mine`` 与写操作不走此函数。
    """
    if kind not in _OWNER_LOOKUP:
        raise ValueError(f"未知审核类型: {kind!r}")
    public = qs.filter(public_q(kind))
    if action != "retrieve":
        return public
    if not user or not getattr(user, "is_authenticated", False):
        return public
    if user.has_perm("reviews.moderate"):
        return qs
    lookup = _OWNER_LOOKUP[kind]
    return (public | qs.filter(**{lookup: user})).distinct()
