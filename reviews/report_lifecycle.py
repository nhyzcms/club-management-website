"""举报案状态机（ADR-0003：状态转移不是访问控制，与 permission_classes 分离）。"""
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from common.targets import host_ref
from messaging.models import Comment, CommentThread
from messaging.services import (
    MessagingError,
    delete_comment_for_report,
    host_of,
    notify_many,
    notify_perm,
)

from .discipline import mute_user_for_report

from .lifecycle import REMOVE, apply
from .models import ReportCase, ReportFiling, Review
from .visibility import public_q

TARGET_NEWS = "news"
TARGET_ACTIVITY = "activity"
TARGET_TUTORIAL = "tutorial"
TARGET_COMMENT = "comment"
TARGET_USER = "user"
TARGET_TYPES = (TARGET_NEWS, TARGET_ACTIVITY, TARGET_TUTORIAL, TARGET_COMMENT, TARGET_USER)

_FK = {
    TARGET_NEWS: "news",
    TARGET_ACTIVITY: "activity",
    TARGET_TUTORIAL: "tutorial",
    TARGET_COMMENT: "comment",
    TARGET_USER: "reported_user",
}


class ReportDenied(Exception):
    """当前状态或对象不允许该举报动作。"""


def target_type_of(case):
    """举报对象类型。先走 ContentTarget，回落旧列，最后认「被举报用户」。

    ``reported_user`` 不参与 ContentTarget（「人」不是「内容」，用户删除后举报案
    要留档），所以它是这条链上唯一的非 target 分支。
    """
    ref = host_ref(case)
    if ref is not None:
        return ref[0]
    if case.reported_user_id:
        return TARGET_USER
    return None


def target_id_of(case):
    ref = host_ref(case)
    if ref is not None:
        return ref[1]
    return case.reported_user_id


def file(*, actor, target_type, target_id, reason):
    """提交一份举报：有进行中案则附上，否则开新案。"""
    reason = (reason or "").strip()
    if not reason:
        raise ReportDenied("请填写举报理由")
    if target_type not in TARGET_TYPES:
        raise ReportDenied("不支持的举报对象")
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        raise ReportDenied("不支持的举报对象") from None

    target = _load_target(target_type, target_id)
    if target is None:
        raise ReportDenied("不能举报该对象")
    if _is_own(actor, target_type, target):
        raise ReportDenied("不能举报自己的内容")
    if not _visible_as_reader(actor, target_type, target):
        raise ReportDenied("不能举报该对象")

    fk = _FK[target_type]
    created = False
    try:
        with transaction.atomic():
            open_case = (
                ReportCase.objects.select_for_update()
                .filter(status=ReportCase.STATUS_OPEN, **{fk: target})
                .first()
            )
            if open_case is None:
                open_case = ReportCase.objects.create(
                    status=ReportCase.STATUS_OPEN, **{fk: target},
                )
                created = True
            if ReportFiling.objects.filter(case=open_case, reporter=actor).exists():
                raise ReportDenied("你已举报过该对象")
            ReportFiling.objects.create(case=open_case, reporter=actor, reason=reason)
    except IntegrityError as exc:
        raise ReportDenied("你已举报过该对象") from exc
    if created:  # 首次立案 → 通知处理者（追加举报不重复打扰）
        notify_perm(
            "review",
            "report_submitted",
            "reviews.handle_report",
            actor=actor,
            payload={
                "type": target_type,
                "id": open_case.pk,
                "url": "/reviews",
            },
        )
    return open_case


def dismiss(case, actor, *, comment):
    """驳回进行中案。理由必填。"""
    if case.status != ReportCase.STATUS_OPEN:
        raise ReportDenied("该举报案已结案")
    comment = (comment or "").strip()
    if not comment:
        raise ReportDenied("请填写驳回理由")
    case.status = ReportCase.STATUS_DISMISSED
    case.moderated_by = actor
    case.moderated_at = timezone.now()
    case.moderation_note = comment
    case.save(update_fields=[
        "status", "moderated_by", "moderated_at", "moderation_note", "updated_at",
    ])
    _notify_reporters(case, actor)
    return case


def _notify_reporters(case, actor):
    """举报处理结果：通知该案全部举报人。"""
    reporters = [filing.reporter for filing in case.filings.select_related("reporter")]
    if not reporters:
        return
    notify_many(
        reporters,
        "review",
        "report_resolved",
        actor=actor,
        payload={
            "type": "report",
            "id": case.pk,
            "result": "dismissed" if case.status == ReportCase.STATUS_DISMISSED else "upheld",
        },
    )


def uphold(case, actor, *, comment="", ends_at=None):
    """成立并执行默认处置。``ends_at`` 仅用户对象：省略即永久。"""
    if case.status != ReportCase.STATUS_OPEN:
        raise ReportDenied("该举报案已结案")
    note = (comment or "").strip()
    try:
        _dispose(case, actor, note=note, ends_at=ends_at)
    except MessagingError as exc:
        raise ReportDenied(exc.detail) from exc
    case.status = ReportCase.STATUS_UPHELD
    case.moderated_by = actor
    case.moderated_at = timezone.now()
    case.moderation_note = note
    case.save(update_fields=[
        "status", "moderated_by", "moderated_at", "moderation_note", "updated_at",
    ])
    _notify_reporters(case, actor)
    return case


def _load_target(target_type, target_id):
    if target_type == TARGET_NEWS:
        from news.models import News
        return News.objects.filter(pk=target_id).first()
    if target_type == TARGET_ACTIVITY:
        from activities.models import Activity
        return Activity.objects.filter(pk=target_id).first()
    if target_type == TARGET_TUTORIAL:
        from tutorials.models import Tutorial
        return Tutorial.objects.filter(pk=target_id).first()
    if target_type == TARGET_COMMENT:
        return (
            Comment.objects.select_related(
                "thread", "thread__news", "thread__activity", "thread__task", "author",
            )
            .filter(pk=target_id)
            .first()
        )
    return User.objects.filter(pk=target_id).first()


def _is_own(actor, target_type, target):
    if target_type == TARGET_NEWS:
        return target.author_id == actor.pk
    if target_type == TARGET_ACTIVITY:
        return target.creator_id == actor.pk
    if target_type == TARGET_TUTORIAL:
        return target.uploader_id == actor.pk
    if target_type == TARGET_COMMENT:
        return target.author_id == actor.pk
    return target.pk == actor.pk


def _visible_as_reader(actor, target_type, target):
    """对象须对举报人作为普通读者可见（不含作者预览 / 审核员全量）。"""
    if target_type == TARGET_NEWS:
        from news.models import News
        return (
            News.objects.filter(pk=target.pk, is_published=True)
            .filter(public_q("news"))
            .exists()
        )
    if target_type == TARGET_ACTIVITY:
        from activities.models import Activity
        return Activity.objects.filter(pk=target.pk).filter(public_q("activity")).exists()
    if target_type == TARGET_TUTORIAL:
        from tutorials.models import Tutorial
        return Tutorial.objects.filter(pk=target.pk).filter(public_q("tutorial")).exists()
    if target_type == TARGET_COMMENT:
        if target.deleted_at:
            return False
        thread = target.thread
        if thread.status == CommentThread.STATUS_CLOSED:
            return False
        return _host_public_to_reader(actor, host_of(thread))
    return bool(target.is_active)


def _host_public_to_reader(actor, host):
    name = host._meta.model_name
    if name == "news":
        from news.models import News
        return (
            News.objects.filter(pk=host.pk, is_published=True)
            .filter(public_q("news"))
            .exists()
        )
    if name == "activity":
        from activities.models import Activity
        return Activity.objects.filter(pk=host.pk).filter(public_q("activity")).exists()
    if name == "task":
        return bool(actor and getattr(actor, "is_authenticated", False))
    return False


def _dispose(case, actor, *, note, ends_at):
    kind = target_type_of(case)
    if kind in (TARGET_NEWS, TARGET_ACTIVITY, TARGET_TUTORIAL):
        _remove_publication(case, actor, note)
        return
    if kind == TARGET_COMMENT:
        comment = case.comment
        if comment is not None:
            delete_comment_for_report(comment, actor)
        return
    if kind == TARGET_USER:
        user = case.reported_user
        if user is None:
            return
        mute_user_for_report(actor, user, reason=note, ends_at=ends_at)


def _remove_publication(case, actor, note):
    """把被举报并成立的内容下架：找到它的审核记录并执行 remove。

    切读期同时认 target 与旧列；``comment`` 型举报没有对应的审核记录（评论不经
    审核发布），原样返回。
    """
    ref = host_ref(case)
    if ref is None:
        return
    kind, object_id = ref
    if kind not in ("news", "activity", "tutorial"):
        return
    review = Review.objects.filter(
        Q(target__kind=kind, target__object_id=object_id) | Q(**{kind: object_id}),
    ).first()
    if review is None or review.status == Review.STATUS_REMOVED:
        return
    if review.status != Review.STATUS_APPROVED:
        return
    apply(REMOVE, review, actor, comment=note)
