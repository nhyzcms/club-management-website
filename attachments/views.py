"""统一附件端点：POST /attachments/（上传）、DELETE /attachments/{id}/（删除）。"""
import logging

from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .create import PARENTS, create_attachment, parent_of, spec_for
from .models import Attachment
from .permissions import can_manage_parent_attachments, can_upload_to_parent
from .serializers import AttachmentSerializer
from .validation import feedback_quota_error, upload_error

log = logging.getLogger(__name__)


class AttachmentViewSet(
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """统一附件：仅提供创建（上传）与删除；列表随父级详情返回。"""

    queryset = Attachment.objects.select_related(
        "uploaded_by", "task", "feedback", "news",
        "submission", "submission__activity",
        "exhibit", "exhibit__activity",
    )
    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]

    # ── 上传：POST /attachments/ ──
    def create(self, request, *args, **kwargs):
        file = request.FILES.get("file")
        if not file:
            return Response(
                {"detail": "请选择文件"}, status=status.HTTP_400_BAD_REQUEST,
            )

        err = upload_error(file)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        specified = []
        for spec in PARENTS.values():
            if not spec.endpoint:
                continue
            pid = request.data.get(f"{spec.key}_id")
            if pid not in (None, ""):
                specified.append((spec, pid))
        endpoint_ids = " / ".join(f"{s.key}_id" for s in PARENTS.values() if s.endpoint)
        if len(specified) != 1:
            return Response(
                {"detail": f"必须且只能指定一个父级（{endpoint_ids}）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        spec, pid = specified[0]
        try:
            parent = spec.model.objects.get(pk=pid)
        except (spec.model.DoesNotExist, ValueError, TypeError):
            return Response(
                {"detail": "指定的父级不存在"}, status=status.HTTP_404_NOT_FOUND,
            )

        if not can_upload_to_parent(request.user, parent):
            return Response(
                {"detail": "无权操作此父级的附件"}, status=status.HTTP_403_FORBIDDEN,
            )

        # 反馈附件配额（仅反馈父级；同步 / tus 共用的校验收在 validation）
        quota_err = feedback_quota_error(parent, file.size)
        if quota_err:
            return Response({"detail": quota_err}, status=status.HTTP_400_BAD_REQUEST)

        attachment = create_attachment(user=request.user, parent=parent, file=file)
        return Response(
            AttachmentSerializer(attachment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ── 删除：DELETE /attachments/{id}/ ──
    def destroy(self, request, *args, **kwargs):
        attachment = self.get_object()
        parent = parent_of(attachment)
        spec = spec_for(parent)
        # 反馈证据链：了结后只有持 read_feedback 者能删（审计 M-9）。
        # 上传在了结时已锁死；删除若不锁，创建者/上传者可把证据抽走，审计链断裂。
        if (
            spec is not None and spec.key == "feedback" and parent is not None
            and parent.status != "pending"
        ):
            if not request.user.has_perm("reviews.read_feedback"):
                return Response(
                    {"detail": "反馈已了结，证据附件仅处理人可删除"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            log.info(
                "feedback evidence deleted after close: attachment=%s feedback=%s by=%s",
                attachment.pk, parent.pk, request.user.pk,
            )
        # 统一规则；此外附件上传者始终可删自己上传的（用户故事 #12）。
        allowed = (
            can_manage_parent_attachments(request.user, parent)
            or attachment.uploaded_by_id == request.user.pk
        )
        if not allowed:
            return Response(
                {"detail": "无权删除此附件"}, status=status.HTTP_403_FORBIDDEN,
            )
        attachment.delete()  # post_delete 信号回收磁盘文件
        return Response(status=status.HTTP_204_NO_CONTENT)
