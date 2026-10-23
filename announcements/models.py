"""全站弹窗公告（ADR-0042）。

一条 ``Announcement`` = 一次「全站弹窗 + 站内通知 +（可选）邮件」的发布。

**为什么文档只存原件、不转站内富文本**：需求要求「保持原格式 / 排版不变」。把 PDF 抽成
文字、或用 mammoth 把 .docx 转成 HTML，都会丢分页、字体、表格边框、页眉页脚等版面信息。
所以这里只做「类型 + 大小」校验并原样保存，浏览端用 pdf.js（PDF）/ docx-preview（.docx）
按原排版渲染，另附「下载原件」——与关于页的文档保真导入同一条路子。

**已读口径**：``AnnouncementRead`` 一人一行（唯一约束），关闭弹窗即写入；同一公告跨设备
只算一次。受众为「全站」时匿名访客没有行可写，前端用 localStorage 记住「已看过」，
因此后台的「阅读量」只统计登录用户的已读人数（见 ``services.stats``）。
"""
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# 文档上限：与关于页文档保真导入一致（20MB）。再大就不适合塞进弹窗（3M 带宽）。
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

DOCUMENT_PDF = "pdf"
DOCUMENT_DOCX = "docx"
DOCUMENT_CHOICES = [
    (DOCUMENT_PDF, "PDF"),
    (DOCUMENT_DOCX, "Word (.docx)"),
]

# content_type → 类型（部分浏览器上传 .docx 会报 octet-stream，故还要看扩展名）
DOCUMENT_CONTENT_TYPES = {
    "application/pdf": DOCUMENT_PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DOCUMENT_DOCX,
}


def document_kind_of(name: str, content_type: str = "") -> str:
    """由文件名 / MIME 判定文档类型；不支持的类型返回空串。"""
    ext = os.path.splitext((name or "").lower())[1]
    if ext == ".pdf":
        return DOCUMENT_PDF
    if ext == ".docx":
        return DOCUMENT_DOCX
    return DOCUMENT_CONTENT_TYPES.get((content_type or "").lower(), "")


def announcement_document_path(instance, filename):
    """扁平存储 + 随机名：announcements/<uuid>.<ext>（原件名另存 document_name）。"""
    ext = os.path.splitext(filename or "")[1].lower() or ".bin"
    return f"announcements/{uuid.uuid4().hex}{ext}"


class Announcement(models.Model):
    """一条全站弹窗公告。"""

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "草稿"),
        (STATUS_PUBLISHED, "已发布"),
        (STATUS_ARCHIVED, "已下线"),
    ]

    AUDIENCE_ALL = "all"
    AUDIENCE_REGISTERED = "registered"
    AUDIENCE_VERIFIED = "verified"
    AUDIENCE_ADMIN = "admin"
    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL, "全站（含未登录访客）"),
        (AUDIENCE_REGISTERED, "注册用户（已登录）"),
        (AUDIENCE_VERIFIED, "认证用户"),
        (AUDIENCE_ADMIN, "管理员"),
    ]

    title = models.CharField("标题", max_length=200)
    summary = models.TextField(
        "正文", blank=True, default="",
        help_text="弹窗顶部的纯文本说明（可选）。文档类公告可以只上传文档。",
    )
    document = models.FileField(
        "文档原件（PDF / .docx）", upload_to=announcement_document_path, blank=True,
        help_text="按原排版渲染，不转站内富文本。上限 20MB。",
    )
    document_name = models.CharField("文档原名", max_length=255, blank=True, default="")
    document_kind = models.CharField(
        "文档类型", max_length=8, choices=DOCUMENT_CHOICES, blank=True, default="",
    )
    document_size = models.PositiveBigIntegerField("文档大小（字节）", default=0)

    audience = models.CharField(
        "发布范围", max_length=16, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL,
    )
    send_email = models.BooleanField(
        "同时发送邮件", default=False,
        help_text="发送到用户已认证的绑定邮箱（未认证邮箱不发，避免误发到拼写错误的地址）。",
    )

    status = models.CharField(
        "状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT,
    )
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    expires_at = models.DateTimeField(
        "下线时间", null=True, blank=True,
        help_text="留空 = 一直弹到手动下线。到点后不再弹出，但站内通知里仍可回看。",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_announcements", verbose_name="发布人",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "全站弹窗公告"
        verbose_name_plural = "全站弹窗公告"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "published_at"]),
        ]
        permissions = [
            ("manage_announcements", "管理全站弹窗公告"),
        ]

    def __str__(self):
        return self.title

    # ---- 校验 / 派生 -----------------------------------------------------
    def clean(self):
        super().clean()
        if not (self.summary or "").strip() and not self.document:
            raise ValidationError("正文与文档至少要有一个：只上传文档也可以。")
        if self.document and not self.document_kind:
            raise ValidationError({"document": "仅支持 PDF 或 .docx"})
        if self.expires_at and self.published_at and self.expires_at <= self.published_at:
            raise ValidationError({"expires_at": "下线时间必须晚于发布时间。"})

    @property
    def has_document(self) -> bool:
        return bool(self.document)

    def is_live(self, now=None) -> bool:
        """已发布、已到发布时刻、未过下线时间。"""
        if self.status != self.STATUS_PUBLISHED or self.published_at is None:
            return False
        now = now or timezone.now()
        if self.published_at > now:
            return False
        return self.expires_at is None or self.expires_at > now


class AnnouncementRead(models.Model):
    """已读台账：一人 × 一条公告一行（关闭弹窗即写入，跨设备只算一次）。"""

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE,
        related_name="reads", verbose_name="公告",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="announcement_reads", verbose_name="用户",
    )
    read_at = models.DateTimeField("已读时间", auto_now_add=True)

    class Meta:
        verbose_name = "公告已读"
        verbose_name_plural = "公告已读"
        ordering = ["-read_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "user"], name="announcement_read_unique",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} read announcement {self.announcement_id}"
