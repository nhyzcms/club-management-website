"""tus 可续传上传接入（#19）：drf-tus 的 UploadViewSet 子类 + 完成钩子。

大文件（超过同步上限的图/视频，≤ tus 上限）走 tus 通路 ``POST /uploads/files/ …``：

- 创建时按 Upload-Metadata 声明父级，校验权限（复用 ``can_upload_to_parent``，含反馈
  carve-out）+ 尺寸/类型分档（超 tus 上限拒、非图/视频超同步上限拒）+ 反馈配额。
- 完成时（finished 信号）把文件搬到 ``attachments/`` 并建统一 ``Attachment``，复核权限
  （父级状态可能已变——反馈审结、任务关闭——复核失败即丢弃上传）。

小文件（≤ 同步上限）仍走同步 ``POST /attachments/``，不经过此处。
"""
import json
import logging
import os

from django.core.files import File
from django.dispatch import receiver
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rest_framework_tus import constants as tus_constants
from rest_framework_tus.signals import finished
from rest_framework_tus.views import UploadViewSet

from common.policy import format_byte_cap, get_policy

from .create import PARENTS, create_attachment
from .models import TusUpload
from .permissions import can_upload_to_parent
from .validation import classify_file_type, extension_error, feedback_quota_error

logger = logging.getLogger(__name__)


def sweep_stale_tus_uploads():
    """惰性回收过期 / 被放弃的 tus 上传：删除 ``expires`` 已过的会话行。

    drf-tus 创建时盖 ``expires``（仅用于响应头），**自身无清理任务**——故由本应用在每次
    创建时顺带扫描（仿 ``proposals.views.transition_overdue_proposals`` 的自愈式清理，无需
    cron）。``TusUpload.delete`` 会回收临时分片 + 落地副本，故行与文件一并清除。
    """
    stale = TusUpload.objects.filter(expires__isnull=False, expires__lt=timezone.now())
    for upload in stale:
        upload.delete()


def _request_metadata(request):
    return getattr(request, tus_constants.UPLOAD_METADATA_FIELD_NAME, {}) or {}


def _request_upload_length(request):
    return getattr(request, tus_constants.UPLOAD_LENGTH_FIELD_NAME, -1)


def _resolve_parent(meta):
    """从 tus metadata 解析父级对象；返回 (parent, kind) 或 (None, None)。

    只认注册表 ``endpoint=True`` 的增量父级（task / feedback / news）；作品 / 展品
    不走 tus（ADR 0012）。
    """
    ptype = (meta.get("parent_type") or "").strip()
    raw = meta.get("parent_id")
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None, None
    spec = PARENTS.get(ptype)
    if spec is None or not spec.endpoint:
        return None, None
    try:
        return spec.model.objects.get(pk=pid), ptype
    except spec.model.DoesNotExist:
        return None, None


def _model_metadata(instance):
    """读取 TusUpload.upload_metadata 为 dict（jsonfield 存的是 JSONString/str，非 dict）。"""
    raw = instance.upload_metadata
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


class TusUploadViewSet(UploadViewSet):
    """tus 上传端点：在 drf-tus 的创建流程前加 父级 / 权限 / 尺寸类型 / 配额 校验。"""

    permission_classes = [IsAuthenticated]

    @property
    def max_file_size(self):
        # Admin edits apply without restart (drf-tus reads getattr(self, 'max_file_size')).
        return get_policy().tus_media_max_bytes

    def create(self, request, *args, **kwargs):
        sweep_stale_tus_uploads()  # 自愈式回收过期/被放弃的上传（drf-tus 自身无清理任务）
        meta = _request_metadata(request)
        parent, _kind = _resolve_parent(meta)
        if parent is None:
            return Response(
                {"detail": "缺少或无效的父级（Upload-Metadata 需带 parent_type 与 parent_id）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # 权限：反馈在此之上做了 carve-out（仅署名创建者 + 审结前，排除社长）
        if not can_upload_to_parent(request.user, parent):
            return Response({"detail": "无权为此父级上传附件"}, status=status.HTTP_403_FORBIDDEN)

        upload_length = _request_upload_length(request)
        file_type = classify_file_type((meta.get("filetype") or "").strip())
        sync_cap = get_policy().sync_upload_max_bytes
        # 超过同步上限必须是图/视频（其余类型只能走同步通路）
        if upload_length > sync_cap and file_type not in ("image", "video"):
            return Response(
                {"detail": f"超过 {format_byte_cap(sync_cap)} 的文件必须是图片或视频"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # 反馈配额（与同步通路同一处校验）
        quota_err = feedback_quota_error(parent, upload_length)
        if quota_err:
            return Response({"detail": quota_err}, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)

    def get_success_headers(self, data):
        # 不依赖 rest_framework_tus 命名空间的 reverse（本端点用独立路由）；按 guid 直建 Location。
        guid = data.get("guid") if isinstance(data, dict) else None
        return {"Location": f"/uploads/files/{guid}/"} if guid else {}


@receiver(finished, sender=TusUpload)
def create_attachment_from_tus(sender, instance, **kwargs):
    """tus 上传完成：复核权限后把文件搬成统一 Attachment，并清理 tus 的文件副本。

    不能在此删除 TusUpload 行——drf-tus 的保存处理器在 ``finish()`` 之后还会
    ``upload.save()``，删了会被重新落库。故只清理文件副本（临时分片 + 落地副本，Attachment
    持有独立副本）；会话行由 ``sweep_stale_tus_uploads`` 在下次创建时按 ``expires`` 惰性回收
    （drf-tus 自身无清理任务）。复核失败（父级状态已变 / 用户已删）则不建附件，仅清理文件。
    """
    meta = _model_metadata(instance)
    parent, _kind = _resolve_parent(meta)
    user = instance.user
    if parent is None or user is None or not can_upload_to_parent(user, parent):
        logger.info("tus 完成但权限复核失败，丢弃 %s", instance.guid)
        _cleanup_tus_files(instance)
        return

    filename = meta.get("filename") or f"{instance.guid}.bin"

    # 与同步通路同一条扩展名闸门（审计 M-1）：tus 原先只在创建时看尺寸分档，
    # 完成钩子不校验扩展名，`.html` 可以直接落进 attachments/ 公开目录。
    ext_err = extension_error(filename)
    if ext_err:
        logger.warning("tus 上传被扩展名闸门拒绝 %s（%s）", instance.guid, filename)
        _cleanup_tus_files(instance)
        return

    if not instance.uploaded_file:
        logger.warning("tus 完成但无落地文件 %s", instance.guid)
        return

    with instance.uploaded_file.open("rb") as content:
        wrapped = File(content, name=filename)
        wrapped.content_type = meta.get("filetype") or ""
        create_attachment(user=user, parent=parent, file=wrapped)
    _cleanup_tus_files(instance)  # 搬运完成：回收落地副本 + 临时分片（会话行由 sweep 惰性回收）


def _cleanup_tus_files(instance):
    """回收 tus 的落地文件副本与临时分片（Attachment 已持独立副本）；FS 故障不冒泡。"""
    try:
        if instance.uploaded_file:
            instance.uploaded_file.delete(save=False)
    except Exception:  # noqa: BLE001
        logger.warning("清理 tus 落地文件失败 %s", instance.guid, exc_info=True)
    tmp = getattr(instance, "temporary_file_path", None)
    if tmp:
        try:
            os.remove(tmp)
        except OSError:
            pass
