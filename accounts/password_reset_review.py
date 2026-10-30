"""密码重置申请的审核队列（审核台「密码重置」桌）。

列表 + 批准 / 驳回。访问控制 = ``accounts.review_password_reset``（见 permissions）。
写路径全部复用 ``accounts.password_reset`` 服务，保证与管理员后台动作语义一致。
"""
from django.urls import reverse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PasswordResetRequest
from .password_reset import PasswordResetError, approve_request, reject_request
from .permissions import CanReviewPasswordReset


class PasswordResetRequestSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    user_id = serializers.IntegerField(read_only=True)
    real_name = serializers.SerializerMethodField()
    proof_url = serializers.SerializerMethodField()
    reviewed_by = serializers.SerializerMethodField()
    # B2：模型字段统一为 moderated_at / moderation_note，对外名保持不变
    reviewed_at = serializers.DateTimeField(source="moderated_at", read_only=True)
    review_note = serializers.CharField(source="moderation_note", read_only=True)

    class Meta:
        model = PasswordResetRequest
        fields = [
            "id", "user_id", "username", "real_name", "identifier", "contact", "note",
            "status", "created_at", "reviewed_at", "reviewed_by", "review_note",
            "reset_at", "proof_url",
        ]
        read_only_fields = fields

    def get_real_name(self, obj):
        try:
            return obj.user.profile.real_name or ""
        except Exception:  # Profile.DoesNotExist 等（防御：老数据）
            return ""

    def get_proof_url(self, obj):
        return reverse("password_reset_proof_file", args=[obj.pk])

    def get_reviewed_by(self, obj):
        reviewer = obj.moderated_by
        if reviewer is None:
            return None
        return {"id": reviewer.id, "username": reviewer.username}


class PasswordResetRequestViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PasswordResetRequestSerializer
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        qs = (
            PasswordResetRequest.objects
            .select_related("user", "user__profile", "moderated_by")
            .order_by("-created_at", "-id")
        )
        if getattr(self, "action", None) == "list":
            status_param = self.request.query_params.get(
                "status", PasswordResetRequest.STATUS_PENDING,
            )
            if status_param:
                qs = qs.filter(status=status_param)
        return qs

    def get_permissions(self):
        return [IsAuthenticated(), CanReviewPasswordReset()]

    def _note(self):
        data = self.request.data if hasattr(self.request, "data") else {}
        return (data.get("note") or "").strip()

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        obj = self.get_object()
        try:
            obj = approve_request(obj, reviewer=request.user, note=self._note())
        except PasswordResetError as exc:
            return Response(
                {"error": exc.message, "reason": exc.reason}, status=exc.status,
            )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        obj = self.get_object()
        try:
            obj = reject_request(obj, reviewer=request.user, note=self._note())
        except PasswordResetError as exc:
            return Response(
                {"error": exc.message, "reason": exc.reason}, status=exc.status,
            )
        return Response(self.get_serializer(obj).data)
