import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


# 封面图上限与允许类型（序列化器与 upload_cover 端点共用；与正文内嵌图同规格）
COVER_MAX_SIZE = 5 * 1024 * 1024
COVER_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def cover_upload_path(instance, filename):
    """新闻封面图：统一存到 news_covers/，文件名用 uuid 防冲突。"""
    ext = os.path.splitext(filename)[1]
    return f"news_covers/{uuid.uuid4().hex}{ext}"


def cover_thumbnail_path(instance, filename):
    """封面缩略图：news_covers/thumbs/ 下（文件名由序列化器按封面名生成）。"""
    return f"news_covers/thumbs/{filename}"


class News(models.Model):
    """新闻 / 公告。"""

    title = models.CharField("标题", max_length=200)
    summary = models.CharField("摘要", max_length=280, blank=True, default="")
    content = models.TextField("正文（HTML）", blank=True, default="")
    cover_image = models.ImageField("封面图", upload_to=cover_upload_path, blank=True)
    cover_thumbnail = models.ImageField("封面缩略图", upload_to=cover_thumbnail_path, blank=True)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="news", verbose_name="作者",
    )
    tags = models.ManyToManyField(
        "common.Tag", blank=True, related_name="news", verbose_name="标签",
    )

    featured = models.BooleanField("头条", default=False)
    views = models.PositiveIntegerField("阅读人数", default=0)
    is_published = models.BooleanField("已发布", default=True)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    # 服务端草稿区已拆到 ``NewsDraft``（B7）：这里只留只读转发属性，API 契约不变。
    # 拆的理由：草稿是「另一件事」，塞在主表上有两个代价——每次查新闻都拖着四个
    # 用不上的列；草稿结构被主表字段钉死（想多存一个字段就要给新闻表加列）。

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "新闻"
        verbose_name_plural = "新闻"
        ordering = ["-published_at", "-created_at"]
        permissions = [
            ("manage_news", "可管理新闻"),
        ]

    def __str__(self):
        return self.title

    # ---- 草稿转发属性（只读；写路径直接操作 NewsDraft）------------------
    # 保留这组属性是为了让 serializer / 模板 / 既有调用点不必到处改；
    # 代价是「读草稿」会多一次查询，但 OneToOne 反向访问器会把结果缓存到实例上，
    # 同一实例重复读不重复查库。
    @property
    def draft(self):
        """草稿对象；无则 None（不抛 DoesNotExist，调用方少写 try）。

        用反向 OneToOne 访问器 ``draft_record``：首次访问后 Django 会把结果
        缓存进实例的 fields_cache，同一实例反复读不重复查库。
        """
        if not self.pk:
            return None
        try:
            return self.draft_record
        except NewsDraft.DoesNotExist:
            return None

    @property
    def draft_title(self):
        d = self.draft
        return d.title if d else ""

    @property
    def draft_summary(self):
        d = self.draft
        return d.summary if d else ""

    @property
    def draft_content(self):
        d = self.draft
        return d.content if d else ""

    @property
    def draft_saved_at(self):
        d = self.draft
        return d.saved_at if d else None


class NewsDraft(models.Model):
    """已发布新闻的「待发布修改」暂存区（B7）。

    生命周期：编辑已发布新闻 → 自动保存写这里 → 公开页仍显示旧版 →
    点「保存修改」时随更新消费清空（见 ``news/serializers.py`` 的 update）。

    未发布稿件不用这张表：它的自动保存直接写正文（稿件本体即草稿，列表可见）。
    """

    news = models.OneToOneField(
        News, on_delete=models.CASCADE, related_name="draft_record", verbose_name="新闻",
    )
    title = models.CharField("标题", max_length=200, blank=True, default="")
    summary = models.CharField("摘要", max_length=280, blank=True, default="")
    content = models.TextField("正文（HTML）", blank=True, default="")
    # 用 default 而非 auto_now：迁移历史草稿时要保住原来的保存时间。
    saved_at = models.DateTimeField("保存时间", default=timezone.now)

    class Meta:
        verbose_name = "新闻草稿"
        verbose_name_plural = "新闻草稿"
        ordering = ["-saved_at"]

    def __str__(self):
        return f"草稿 · {self.title or self.news_id}"


class NewsView(models.Model):
    """单条新闻的去重阅读记录。

    reader_key 统一登录 / 匿名两种情况：登录用户 = ``"user:{pk}"``，
    匿名 = ``"ip:{sha256(REMOTE_ADDR)}"``（存 hash 不存明文 IP）。
    ``News.views`` 是去重后的累计读者数缓存。
    """

    news = models.ForeignKey(
        News, on_delete=models.CASCADE, related_name="view_records",
        verbose_name="新闻",
    )
    reader_key = models.CharField("读者标识", max_length=80)
    viewed_at = models.DateTimeField("阅读时间", auto_now_add=True)

    class Meta:
        verbose_name = "阅读记录"
        verbose_name_plural = "阅读记录"
        unique_together = ["news", "reader_key"]

    def __str__(self):
        return f"{self.news_id}:{self.reader_key}"
