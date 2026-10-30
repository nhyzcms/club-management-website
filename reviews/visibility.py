"""公开可见性：审核轴只门控「公开展示」，不改对象自身生命周期。"""
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q

from .models import Review

_RELATED_NAME = {
    "news": "review",
    "activity": "publication_review",
    "tutorial": "review",
}
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


def related_name(obj):
    """对象上审核行的 related_name（新闻/教程 ``review``，活动 ``publication_review``）。"""
    name = _RELATED_NAME.get(obj._meta.model_name)
    if name is None:
        raise TypeError(f"{type(obj).__name__} 没有挂审核行")
    return name


def owner_id(obj):
    """对象作者/发起人/上传者的 pk（新闻 author、活动 creator、教程 uploader）。"""
    attr = _OWNER_ID_ATTR.get(obj._meta.model_name)
    if attr is None:
        raise TypeError(f"{type(obj).__name__} 没有挂审核行")
    return getattr(obj, attr)


def public_q(kind):
    """公开读的审核轴 ``Q``。

    新闻/教程仅已过审；活动另含尚无审核行（存量 ORM / 测试夹具例外）。
    新闻的 ``is_published`` 是生命周期轴，由新闻适配器自行相交。
    """
    if kind == "news":
        return Q(review__status=Review.STATUS_APPROVED)
    if kind == "activity":
        return (
            Q(publication_review__status=Review.STATUS_APPROVED)
            | Q(publication_review__isnull=True)
        )
    if kind == "tutorial":
        return Q(review__status=Review.STATUS_APPROVED)
    raise ValueError(f"未知审核类型: {kind!r}")


def _review_of(obj):
    try:
        return getattr(obj, related_name(obj))
    except ObjectDoesNotExist:
        return None


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


# 短迁移薄封装：新代码走上面的接口。
def public_news_kwargs():
    return {"is_published": True, "review__status": Review.STATUS_APPROVED}


def public_activity_q():
    return public_q("activity")


def public_tutorial_q():
    return public_q("tutorial")


def review_record_of(obj, related="review"):
    return _review_of(obj)


def review_status_of(obj, related="review"):
    return status_of(obj)


def review_comment_for(obj, user, *, related="review", owner_id=None):
    return comment_for(obj, user)
