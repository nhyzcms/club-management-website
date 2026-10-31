"""统一附件模型。

一张表可挂在任务、意见反馈或新闻上（三个可空外键，CASCADE），用 DB CheckConstraint
强制「恰好一个父级」。删除父级时 CASCADE 连带删除附件行，再由 post_delete
信号（见 signals.py）同步删除磁盘文件——自动回收，无需定时任务。

反向访问器规范化为 ``attachments``（任务/申报/新闻侧）与 ``uploaded_attachments``
（用户侧）：T3 移除旧的内嵌附件模型后，统一模型成为唯一来源，故不再需要
T1 时期的临时前缀 ``unified_*``。
"""
import os
import uuid

from django.conf import settings
from django.db import models


from rest_framework_tus import states as tus_states
from rest_framework_tus.models import AbstractUpload, custom_upload_path


def attachment_upload_path(instance, filename):
    """扁平存储：attachments/<uuid>.<ext>（不再按父级分目录）。"""
    ext = os.path.splitext(filename)[1]
    return f"attachments/{uuid.uuid4().hex}{ext}"


class Attachment(models.Model):
    """统一附件：恰好挂在一个父级（任务、意见反馈或新闻）上。"""

    # B1：双写期把旧列折射到 target（B9 删旧列时一并移除）。

    FILE_TYPE_CHOICES = [
        ("image", "图片"),
        ("video", "视频"),
        ("document", "文档"),
        ("archive", "压缩包"),
        ("other", "其他"),
    ]

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="uploaded_attachments", verbose_name="上传者",
    )
    # B9：5 个旧父级列（task / feedback / news / submission / exhibit）已删。
    # B1 引入的 target 是唯一宿主锚点，指向 ContentTarget 这张 8 选 1 的登记表。
    target = models.ForeignKey(
        "common.ContentTarget", on_delete=models.CASCADE,
        null=True, blank=True, related_name="attachments", verbose_name="内容目标",
    )
    file = models.FileField("文件", upload_to=attachment_upload_path)
    file_type = models.CharField("文件类型", max_length=20, choices=FILE_TYPE_CHOICES)
    file_name = models.CharField("文件名", max_length=255)
    file_size = models.BigIntegerField("文件大小")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "附件"
        verbose_name_plural = "附件"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.file_name


class TusUpload(AbstractUpload):
    """drf-tus 上传会话（attachments 视角）。

    在 AbstractUpload 上补一个 ``user`` 外键——drf-tus 的创建逻辑在模型有 user 字段时
    自动写入 ``request.user``。上传完成（finished 信号）时据此把文件搬成统一 ``Attachment``
    （见 tus.py 的接收器）。临时分片落 BASE_DIR/tmp/uploads；完成后落到 MEDIA/tus_uploaded/，
    再由接收器搬到 attachments/ 并删除本会话。
    """

    uploaded_file = models.FileField(
        "完成文件", upload_to=custom_upload_path, blank=True, null=True, max_length=255,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="tus_uploads", verbose_name="上传者",
    )

    class Meta: # type: ignore
        verbose_name = "tus 上传"
        verbose_name_plural = "tus 上传"

    def delete(self, *args, **kwargs):
        # DONE 态下文件已落到 uploaded_file，删除行时一并回收（搬运到 Attachment 后由接收器删除）
        if self.state == tus_states.DONE and self.uploaded_file:
            self.uploaded_file.delete(save=False)
        super().delete(*args, **kwargs)
