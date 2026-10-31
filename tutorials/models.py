import uuid

from django.conf import settings
from django.db import models

from common.uploads import safe_extension


def tutorial_file_path(instance, filename):
    ext = safe_extension(filename)
    return f"tutorials/{uuid.uuid4().hex}{ext}"


def tutorial_cover_path(instance, filename):
    ext = safe_extension(filename)
    return f"tutorial_covers/{uuid.uuid4().hex}{ext}"


class Tutorial(models.Model):
    """教程集锦条目：视频或文档。公开可见性由统一审核轴门控。"""

    FILE_VIDEO = "video"
    FILE_DOCUMENT = "document"
    FILE_TYPE_CHOICES = [
        (FILE_VIDEO, "视频"),
        (FILE_DOCUMENT, "文档"),
    ]

    title = models.CharField("标题", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    file = models.FileField("文件", upload_to=tutorial_file_path)
    file_type = models.CharField("文件类型", max_length=12, choices=FILE_TYPE_CHOICES)
    file_name = models.CharField("文件名", max_length=255)
    file_size = models.BigIntegerField("文件大小", default=0)
    cover = models.ImageField("封面", upload_to=tutorial_cover_path, blank=True)
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="tutorials", verbose_name="上传者",
    )
    views = models.PositiveIntegerField("播放量", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "教程"
        verbose_name_plural = "教程"
        ordering = ["-created_at"]
        permissions = [
            ("manage_tutorials", "可管理教程"),
        ]

    def __str__(self):
        return self.title


class TutorialView(models.Model):
    """去重播放记录：登录 user:{pk} / 匿名 ip:{sha256}。"""

    tutorial = models.ForeignKey(
        Tutorial, on_delete=models.CASCADE, related_name="view_records", verbose_name="教程",
    )
    reader_key = models.CharField("读者标识", max_length=80)
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "播放记录"
        unique_together = ["tutorial", "reader_key"]


class TutorialFavorite(models.Model):
    """每人每教程至多一次收藏，可撤。"""

    tutorial = models.ForeignKey(
        Tutorial, on_delete=models.CASCADE, related_name="favorites", verbose_name="教程",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="tutorial_favorites", verbose_name="用户",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "教程收藏"
        unique_together = ["tutorial", "user"]
