"""人工通道审核服务（ADR-0006）：通过 / 驳回 / 停用。

Admin 批量动作与 ``/auth/identity-reviews/`` API 共用本模块——政策门禁、
``verified_at`` / ``verified_by``、邮件、会话吊销走同一条路径。访问控制不在此
（ADR-0005：权限由调用方的 ``permission_classes`` / admin ``get_actions`` 判定）。

ADR-0041：通过时设 ``expires_at`` = 通过日 + 认证有效期；驳回清空 ``expires_at``。
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.policy import get_policy
from messaging.services import notify

from .models import IdentityProof, Profile, UserSession, Verification, verification_valid_days
from .permissions import CanReviewIdentity


class VerificationClosed(Exception):
    """验证通道已关闭，无法通过或驳回身份审核。"""


def _require_verification_open():
    if not get_policy().verification_enabled:
        raise VerificationClosed("验证通道已关闭")


def _send(user, subject, message):
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        fail_silently=True,
    )


def revoke_user_sessions(user):
    """立即吊销用户既有会话：删 Django Session 行（强制登出）+ 清 UserSession.is_current。

    is_active=False 只挡新登录；不吊销既有会话的话，被停用账号仍可用当前会话直到过期。
    """
    keys = list(UserSession.objects.filter(user=user).values_list("session_key", flat=True))
    UserSession.objects.filter(user=user).update(is_current=False)
    if keys:
        Session.objects.filter(session_key__in=keys).delete()


def approve_manual(user, reviewer):
    """通过身份审核：manual 通道置 approved（+ verified_at / verified_by / expires_at），并发邮件。

    验证态单一事实源是 Verification 行（ADR-0006）。任一未过期 approved 通道 ⇒ 账号已验证。
    expires_at = 通过日 + 认证有效期（ADR-0041）。
    """
    _require_verification_open()
    now = timezone.now()
    expires_at = now + timedelta(days=verification_valid_days())
    verification, _ = Verification.objects.get_or_create(
        user=user, channel=Verification.CHANNEL_MANUAL,
        defaults={"status": Verification.STATUS_APPROVED, "verified_at": now,
                  "verified_by": reviewer, "expires_at": expires_at},
    )
    if verification.status != Verification.STATUS_APPROVED:
        verification.status = Verification.STATUS_APPROVED
        verification.verified_at = now
        verification.verified_by = reviewer
        verification.expires_at = expires_at
        verification.save(update_fields=["status", "verified_at", "verified_by", "expires_at"])
    notify(
        user,
        "review",
        "identity_resolved",
        actor=reviewer,
        payload={
            "type": "identity",
            "id": user.pk,
            "result": "approved",
            "url": "/profile",
        },
    )
    return verification


def reject_manual(user, reviewer):
    """驳回身份审核：manual 通道置 rejected，并发邮件提示可在面板重交。

    驳回 ≠ 停用账号：账号仍可登录（访客）、可重交证明；仅 manual 通道记驳回态。
    reviewer 保留与 approve 对称的签名，驳回不写入 verified_by。
    """
    _require_verification_open()
    verification, _ = Verification.objects.get_or_create(
        user=user, channel=Verification.CHANNEL_MANUAL,
        defaults={"status": Verification.STATUS_REJECTED},
    )
    if verification.status != Verification.STATUS_REJECTED:
        verification.status = Verification.STATUS_REJECTED
        verification.verified_at = None
        verification.verified_by = None
        verification.expires_at = None
        verification.save(update_fields=["status", "verified_at", "verified_by", "expires_at"])
    notify(
        user,
        "review",
        "identity_resolved",
        actor=reviewer,
        payload={
            "type": "identity",
            "id": user.pk,
            "result": "rejected",
            "url": "/profile",
        },
    )
    return verification


def disable_user(user):
    """停用账号：置 is_active=False，吊销既有会话，并发邮件通知当事人联系信息组。

    账号级动作，与验证通道无关——被停用账号既不能登录、既有会话也被立即吊销。
    验证通道关闭时仍可执行。
    """
    if user.is_active:
        user.is_active = False
        user.save(update_fields=["is_active"])
        revoke_user_sessions(user)
    _send(
        user,
        "账号已被停用 - 南汇一中传媒社",
        "你的账号已被停用。如有疑问，请联系信息组。",
    )
    return user


def _profile_attr(user, name):
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        return ""
    return getattr(profile, name, "") or ""


class IdentityProofBriefSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = IdentityProof
        fields = ["id", "uploaded_at", "url"]
        read_only_fields = fields

    def get_url(self, obj):
        return reverse("identity_proof_file", args=[obj.pk])


class IdentityReviewSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    real_name = serializers.SerializerMethodField()
    identity = serializers.SerializerMethodField()
    verified_by = serializers.SerializerMethodField()
    proofs = serializers.SerializerMethodField()

    class Meta:
        model = Verification
        fields = [
            "id", "user_id", "username", "real_name", "identity",
            "status", "verified_at", "verified_by", "proofs",
        ]
        read_only_fields = fields

    def get_real_name(self, obj):
        return _profile_attr(obj.user, "real_name")

    def get_identity(self, obj):
        return _profile_attr(obj.user, "identity")

    def get_verified_by(self, obj):
        reviewer = obj.verified_by
        if reviewer is None:
            return None
        return {"id": reviewer.id, "username": reviewer.username}

    def get_proofs(self, obj):
        proofs = obj.user.identity_proofs.all()
        return IdentityProofBriefSerializer(proofs, many=True).data


def _verification_closed_payload():
    return Response(
        {"error": "验证通道已关闭", "reason": "verification_closed"},
        status=status.HTTP_403_FORBIDDEN,
    )


class IdentityReviewViewSet(viewsets.ReadOnlyModelViewSet):
    """人工通道审核队列：一用户一行（其 manual Verification），通过 / 驳回 / 停用。"""

    serializer_class = IdentityReviewSerializer
    ordering = ["pk"]

    def get_queryset(self):
        qs = (
            Verification.objects.filter(channel=Verification.CHANNEL_MANUAL)
            .select_related("user", "user__profile", "verified_by")
            .prefetch_related("user__identity_proofs")
            .order_by("pk")
        )
        if getattr(self, "action", None) == "list":
            channel_status = self.request.query_params.get("status", Verification.STATUS_PENDING)
            if channel_status:
                qs = qs.filter(status=channel_status)
        return qs

    def get_permissions(self):
        return [IsAuthenticated(), CanReviewIdentity()]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        verification = self.get_object()
        try:
            approve_manual(verification.user, reviewer=request.user)
        except VerificationClosed:
            return _verification_closed_payload()
        verification.refresh_from_db()
        return Response(self.get_serializer(verification).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        verification = self.get_object()
        try:
            reject_manual(verification.user, reviewer=request.user)
        except VerificationClosed:
            return _verification_closed_payload()
        verification.refresh_from_db()
        return Response(self.get_serializer(verification).data)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        verification = self.get_object()
        disable_user(verification.user)
        verification.refresh_from_db()
        return Response(self.get_serializer(verification).data)
