"""手动重置密码（忘记密码 → 管理员审核）服务层。

流程：
1. 未登录申请人在 ``/auth/password-reset/request/`` 提交账号标识 + 身份证明；
2. 持 ``accounts.review_password_reset`` 的管理员在审核台（/#/reviews 或 /#/m/review）
   的「密码重置」桌核对证明并批准 / 驳回；
3. 批准 = 密码重置为 :data:`DEFAULT_RESET_PASSWORD` + ``Profile.must_change_password``
   + 吊销既有会话。下次登录必须立即改密（见 accounts.middleware）。

与 ``accounts.validity.py``（有效期执行）、``accounts.identity_review.py``（认证审核）
并列：本模块只承担密码重置的写路径；访问控制由调用方（视图 / 序列化器）负责。
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from messaging.services import notify

from .identity_review import revoke_user_sessions
from .models import PasswordResetRequest, Profile, Verification
from .registration_guard import normalize_name

# 管理员重置后的默认密码（须在首次登录时强制修改）。
DEFAULT_RESET_PASSWORD = "123456"


class PasswordResetError(Exception):
    """密码重置审批失败（带可直接返回给前端的中文文案与 reason）。"""

    def __init__(self, message: str, *, reason: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.status = status


def _notify_resolved(request_obj: PasswordResetRequest, reviewer: User) -> None:
    """站内通知当事人（源 review / 事件 password_reset_resolved）。"""
    approved = request_obj.status == PasswordResetRequest.STATUS_APPROVED
    notify(
        request_obj.user,
        "review",
        "password_reset_resolved",
        actor=reviewer,
        payload={
            "type": "password_reset",
            "id": request_obj.pk,
            "result": request_obj.status,
            "url": "/",
            "approved": approved,
        },
    )


def _send_result_email(request_obj: PasswordResetRequest) -> None:
    """有已认证邮箱时补一封邮件（无邮箱 / 发送失败静默，不影响审批结果）。"""
    user = request_obj.user
    if not user.email:
        return
    if request_obj.status == PasswordResetRequest.STATUS_APPROVED:
        subject = "密码已重置 - 南汇一中传媒社"
        body = (
            "你的账号密码已由管理员重置为 123456。\n"
            "请立即登录并修改密码；首次登录会强制要求修改。\n"
            "如非本人申请，请尽快联系信息组。"
        )
    else:
        subject = "密码重置申请未通过 - 南汇一中传媒社"
        body = "你的密码重置申请未通过审核。如有疑问，请联系信息组。"
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        fail_silently=True,
    )


def approve_request(
    request_obj: PasswordResetRequest, reviewer: User, note: str = "",
) -> PasswordResetRequest:
    """批准申请：重置密码为默认值、要求强制改密、吊销所有既有会话。

    幂等性：只有 ``pending`` 可批准；重复批准抛 ``already_reviewed``（前端据此刷新队列）。
    """
    if request_obj.user_id == reviewer.pk:
        raise PasswordResetError(
            "不能审批自己的密码重置申请，请由其他管理员处理。",
            reason="cannot_review_self", status=403,
        )

    with transaction.atomic():
        locked = (
            PasswordResetRequest.objects.select_for_update()
            .select_related("user")
            .get(pk=request_obj.pk)
        )
        if locked.status != PasswordResetRequest.STATUS_PENDING:
            raise PasswordResetError(
                "该申请已被处理，请刷新后查看最新状态。",
                reason="already_reviewed", status=409,
            )
        user = locked.user
        now = timezone.now()

        user.set_password(DEFAULT_RESET_PASSWORD)
        user.save(update_fields=["password"])
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.must_change_password = True
        profile.save(update_fields=["must_change_password"])

        # 已有会话一律失效：否则持有旧会话的人可绕过「首次登录」直接进入站点。
        revoke_user_sessions(user)

        locked.status = PasswordResetRequest.STATUS_APPROVED
        locked.moderated_at = now
        locked.moderated_by = reviewer
        locked.moderation_note = (note or "")[:200]
        locked.reset_at = now
        locked.save(update_fields=[
            "status", "moderated_at", "moderated_by", "moderation_note", "reset_at",
        ])

    _notify_resolved(locked, reviewer)
    _send_result_email(locked)
    return locked


def reject_request(
    request_obj: PasswordResetRequest, reviewer: User, note: str = "",
) -> PasswordResetRequest:
    """驳回申请：只改申请状态（不动账号密码 / 会话）。"""
    with transaction.atomic():
        locked = (
            PasswordResetRequest.objects.select_for_update()
            .select_related("user")
            .get(pk=request_obj.pk)
        )
        if locked.status != PasswordResetRequest.STATUS_PENDING:
            raise PasswordResetError(
                "该申请已被处理，请刷新后查看最新状态。",
                reason="already_reviewed", status=409,
            )
        locked.status = PasswordResetRequest.STATUS_REJECTED
        locked.moderated_at = timezone.now()
        locked.moderated_by = reviewer
        locked.moderation_note = (note or "")[:200]
        locked.save(update_fields=["status", "moderated_at", "moderated_by", "moderation_note"])

    _notify_resolved(locked, reviewer)
    _send_result_email(locked)
    return locked


def resolve_account(identifier: str) -> tuple[User | None, str]:
    """把申请人填写的「用户名 / 邮箱 / 真实姓名」解析成唯一账号。

    返回 ``(user, reason)``：``reason`` 为空 = 命中；``not_found`` = 无匹配；
    ``ambiguous`` = 真实姓名对应多个账号（要求改用用户名 / 邮箱）。
    用户名与邮箱优先（唯一性有保证）；真实姓名只在**恰好一个**账号时采用。
    """
    identifier = (identifier or "").strip()
    if not identifier:
        return None, "not_found"

    user = User.objects.filter(username__iexact=identifier).first()
    if user is not None:
        return user, ""
    user = User.objects.filter(email__iexact=identifier).first()
    if user is not None:
        return user, ""
    verification = (
        Verification.objects.filter(
            channel=Verification.CHANNEL_EMAIL,
            identifier__iexact=identifier,
            status__in=[Verification.STATUS_PENDING, Verification.STATUS_APPROVED],
        )
        .select_related("user")
        .first()
    )
    if verification is not None:
        return verification.user, ""

    name = normalize_name(identifier)
    profiles = list(
        Profile.objects.filter(real_name__iexact=name).select_related("user").order_by("pk")[:2]
    )
    if len(profiles) == 1:
        return profiles[0].user, ""
    if len(profiles) > 1:
        return None, "ambiguous"
    return None, "not_found"


def pending_request_for(user: User) -> PasswordResetRequest | None:
    """该账号是否有待处理申请（用于阻止重复提交）。"""
    return (
        PasswordResetRequest.objects
        .filter(user=user, status=PasswordResetRequest.STATUS_PENDING)
        .order_by("-created_at")
        .first()
    )
