"""账号彻底删除（物理删除，ADR-0052）。

与自服务注销（:mod:`accounts.deletion`，软删除）不同，这里**真的把 ``User`` 行从库里
删掉**，只在 ``AccountDeletionLog`` 里留一条最小审计记录（操作者快照 / 被删账号
id + username / 模式 / 原因 / 时间 / IP）。触发入口：

* Django 后台 User 列表的「强制彻底删除」动作（``accounts.admin``）；
* 管理命令 ``manage.py hard_delete_account``（服务器侧应急）。

**两种内容模式**（由操作者当场选）：

``PURGE``
    该账号写过的内容一并物理删除：新闻、任务、评论、私信、附件、投稿、投票、
    评分、举报……（走 ``user.delete()`` 的级联）。适合「这个号是垃圾/冒用，
    内容也不该留」。

``KEEP``
    内容保留，作者位改挂到本次删除专用的**墓碑账号**（``deleted_<id>_<随机>``，
    ``is_active=False`` + ``deleted_at``）。序列化层（``SimpleUserSerializer``）对
    注销态统一渲染成「该用户已注销」，因此历史内容仍可读、不泄露旧昵称/头像。
    每删一个账号建一个墓碑，避免共用一个墓碑撞 ``(活动, 用户)`` 这类唯一约束。

两种模式都会清掉**个人数据**：实名、邮箱、手机/校牌、认证材料与文件、安全问题、
TOTP/恢复码、会话与设备、登录事件、通知与已读状态、明信片登记（含姓名班级与照片）。
社员名册（``MemberIdentity``）属学校名册数据，只解绑账号、不删名册行。

安全约束：

* 不能删自己；不能删掉**最后一个**可用超级管理员；
* 操作者必须是 ``is_staff``；管理员只能删非管理员的账号，删管理员/超管需要超级管理员；
* 审计记录留存，但目标账号的 id/username 是纯标量，账号删除后仍可追溯。

文件删除放在 ``transaction.on_commit``：数据库回滚时不会出现「文件已删、行还在」。
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from django.apps import apps
from django.contrib.auth.models import User
from django.db import models, transaction
from django.utils import timezone

from .identity_review import revoke_user_sessions
from .models import (
    AccountDeletionLog,
    AccountDevice,
    AccountLifecycle,
    AuthCodeRedemption,
    IdentityProof,
    LoginChallenge,
    LoginEvent,
    PasswordResetRequest,
    Profile,
    RecoveryCode,
    SecurityQuestion,
    StepUpEmailCode,
    StepUpEvent,
    TotpDevice,
    UserSession,
    Verification,
)

MODE_PURGE = "purge"
MODE_KEEP = "keep"
MODE_CHOICES = (
    (MODE_PURGE, "彻底删除内容"),
    (MODE_KEEP, "保留内容并匿名化"),
)

#: 内容归属字段（KEEP 模式改挂墓碑）。全部是「作者/责任人」语义，不含审核人——
#: 审核留痕（moderated_by / verified_by）宁可置空也不该挂到墓碑上。
_OWNED_FIELDS = (
    ("news", "News", "author"),
    ("tasks", "Task", "creator"),
    ("tasks", "Task", "assignee"),
    ("tasks", "TaskClaimRequest", "claimant"),
    ("tutorials", "Tutorial", "uploader"),
    ("messaging", "Comment", "author"),
    ("messaging", "Message", "sender"),
    ("attachments", "Attachment", "uploaded_by"),
    ("activities", "Activity", "creator"),
    ("activities", "Submission", "submitter"),
    ("activities", "Ballot", "voter"),
    ("activities", "ExhibitRating", "user"),
    ("activities", "QuestionnaireResponse", "user"),
    ("activities", "SurveyUpload", "user"),
    ("announcements", "Announcement", "created_by"),
    ("events", "Event", "organizer"),
    ("exam_board", "Exam", "updated_by"),
    ("exam_board", "ExamErrata", "created_by"),
    ("panorama", "Panorama", "created_by"),
    ("reviews", "Feedback", "creator"),
    ("reviews", "ReportFiling", "reporter"),
    ("reviews", "ReportCase", "reported_user"),
    ("reviews", "UserMute", "muted_by"),
)


class HardDeleteError(Exception):
    """彻底删除被拒绝（视图 / 命令负责映射成 HTTP / 退出码）。"""

    def __init__(self, message: str, *, status: int = 400, reason: str = ""):
        self.message = message
        self.status = status
        self.reason = reason
        super().__init__(message)


@dataclass
class HardDeleteResult:
    target_id: int
    target_username: str
    mode: str
    reassigned: dict[str, int] = field(default_factory=dict)
    deleted_files: int = 0
    tombstone_id: int | None = None
    audit_id: int | None = None


def _model(app_label: str, name: str):
    return apps.get_model(app_label, name)


def _collect_files(obj, files: list) -> None:
    """把 ``obj`` 上所有非空文件字段登记到 ``files``（storage + name）。"""
    for f in obj._meta.fields:
        if not isinstance(f, models.FileField):
            continue
        value = getattr(obj, f.name, None)
        if value and getattr(value, "name", ""):
            files.append((value.storage, value.name))


def _delete_on_commit(files: list) -> None:
    """提交后删文件；``on_commit`` 里抛异常会污染响应，所以逐个吞掉并记账。"""
    unique = {(id(storage), name): (storage, name) for storage, name in files}

    def _run():
        for storage, name in unique.values():
            try:
                storage.delete(name)
            except OSError:
                pass

    transaction.on_commit(_run)


def _create_tombstone(user: User) -> User:
    """建本次删除专用的墓碑账号（注销态），用来接管保留内容的作者位。"""
    tombstone = User(
        username=f"deleted_{user.pk}_{secrets.token_hex(4)}",
        email="",
        is_active=False,
    )
    tombstone.set_unusable_password()
    tombstone.save()
    Profile.objects.create(user=tombstone)
    AccountLifecycle.objects.filter(user=tombstone).update(deleted_at=timezone.now())
    return tombstone


def _reassign_owned(user: User, tombstone: User) -> dict[str, int]:
    moved: dict[str, int] = {}
    for app_label, model_name, field_name in _OWNED_FIELDS:
        model = _model(app_label, model_name)
        count = model._default_manager.filter(**{field_name: user}).update(
            **{field_name: tombstone},
        )
        if count:
            moved[f"{app_label}.{model_name}.{field_name}"] = count
    return moved


def _delete_personal_data(user: User, files: list) -> None:
    """删除所有「只属于这个账号」的行，并把要清理的文件登记下来。"""
    profile = Profile.objects.filter(user=user).first()
    if profile is not None:
        _collect_files(profile, files)

    for proof in IdentityProof.objects.filter(user=user):
        _collect_files(proof, files)
    for request in PasswordResetRequest.objects.filter(user=user):
        _collect_files(request, files)

    # 明信片登记含姓名 / 年级 / 班级，属个人数据：连同私有存储里的照片一起清掉。
    postcard_registration = _model("events", "PostcardRegistration")
    postcard_photo = _model("events", "PostcardPhoto")
    registrations = postcard_registration.objects.filter(user=user)
    for photo in postcard_photo.objects.filter(item__registration__in=registrations).select_related():
        _collect_files(photo, files)
    registrations.delete()

    # 登录态：先删 Django Session（立即断线），再删设备 / 事件行。
    revoke_user_sessions(user)
    UserSession.objects.filter(user=user).delete()
    LoginEvent.objects.filter(user=user).delete()
    AccountDevice.objects.filter(user=user).delete()
    LoginChallenge.objects.filter(user=user).delete()

    # 认证 / 安全验证 / 兑换记录。
    Verification.objects.filter(user=user).delete()
    AuthCodeRedemption.objects.filter(user=user).delete()
    SecurityQuestion.objects.filter(user=user).delete()
    StepUpEmailCode.objects.filter(user=user).delete()
    StepUpEvent.objects.filter(user=user).delete()
    TotpDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()

    # 站内通知 / 订阅 / 已读状态 / 公告已读 / 教程收藏 / 收到的禁言。
    from announcements.models import AnnouncementRead
    from messaging.models import MessageReadStatus, Notification, NotificationSubscription
    from reviews.models import UserMute
    from tutorials.models import TutorialFavorite

    Notification.objects.filter(recipient=user).delete()
    NotificationSubscription.objects.filter(user=user).delete()
    MessageReadStatus.objects.filter(user=user).delete()
    AnnouncementRead.objects.filter(user=user).delete()
    TutorialFavorite.objects.filter(user=user).delete()
    UserMute.objects.filter(user=user).delete()


def _collect_cascade_files(user: User, files: list) -> None:
    """PURGE 模式：user.delete() 会级联删掉一批内容，先把它们的文件登记下来。"""
    for rel in user._meta.related_objects:
        f = rel.field
        if f.many_to_many or not getattr(f, "concrete", False):
            continue
        model = rel.related_model
        if model._meta.auto_created:
            continue
        try:
            qs = model._default_manager.filter(**{f.name: user})
        except Exception:  # pragma: no cover - 防御：未来出现不支持过滤的关联
            continue
        for obj in qs.iterator():
            _collect_files(obj, files)


def can_hard_delete(actor: User | None, target: User) -> tuple[bool, str]:
    """权限/保护规则；返回 ``(允许, 拒绝原因)``。命令行走 ``actor=None``（运维通道）。"""
    if target.pk is None:
        return False, "账号不存在。"
    if actor is not None:
        if not (actor.is_active and actor.is_staff):
            return False, "只有管理员可以使用彻底删除。"
        if actor.pk == target.pk:
            return False, "不能彻底删除自己的账号。"
        if target.is_superuser and not actor.is_superuser:
            return False, "只有超级管理员可以彻底删除超级管理员账号。"
        if target.is_staff and not actor.is_superuser:
            return False, "只有超级管理员可以彻底删除管理员账号。"
    if target.is_superuser and target.is_active:
        if not User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk).exists():
            return False, "这是最后一个可用的超级管理员，不能删除。"
    return True, ""


@transaction.atomic
def hard_delete_account(
    user: User,
    *,
    actor: User | None = None,
    mode: str = MODE_KEEP,
    reason: str = "",
    ip: str | None = None,
) -> HardDeleteResult:
    """物理删除 ``user``；``mode`` 决定其内容一起删还是改挂墓碑。"""
    if mode not in (MODE_PURGE, MODE_KEEP):
        raise HardDeleteError("无效的内容模式。", reason="invalid_mode")
    if user is None or user.pk is None:
        raise HardDeleteError("账号不存在。", status=404, reason="user_not_found")

    allowed, why = can_hard_delete(actor, user)
    if not allowed:
        raise HardDeleteError(why, status=403, reason="hard_delete_forbidden")

    target_id = user.pk
    target_username = user.username
    nickname = getattr(getattr(user, "profile", None), "nickname", "") or ""

    # 文件收集：个人数据 + （PURGE 时）将被级联删除的内容。
    files: list = []
    _delete_personal_data(user, files)

    tombstone = None
    reassigned: dict[str, int] = {}
    if mode == MODE_KEEP:
        tombstone = _create_tombstone(user)
        reassigned = _reassign_owned(user, tombstone)
    else:
        _collect_cascade_files(user, files)

    user.delete()

    _delete_on_commit(files)

    audit = AccountDeletionLog.objects.create(
        actor=actor,
        actor_username=getattr(actor, "username", "") or "cli",
        target_id=target_id,
        target_username=target_username,
        target_nickname=nickname[:50],
        mode=mode,
        reason=(reason or "")[:2000],
        ip=ip,
    )

    return HardDeleteResult(
        target_id=target_id,
        target_username=target_username,
        mode=mode,
        reassigned=reassigned,
        deleted_files=len({(id(s), n) for s, n in files}),
        tombstone_id=tombstone.pk if tombstone is not None else None,
        audit_id=audit.pk,
    )
