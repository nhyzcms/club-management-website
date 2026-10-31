from django.db import models

from common.uploads import safe_extension


def about_document_path(instance, filename):
    ext = safe_extension(filename)[1:]
    return f"about_documents/{instance.key}.{ext}"


class SingletonManager(models.Manager):
    """单例管理器：get_solo() 始终返回唯一的那一行（缺失则按默认值创建）。"""

    def get_solo(self):
        obj, _ = self.get_or_create(pk=1, defaults={"title": "关于我们"})
        return obj


class AboutPage(models.Model):
    """站点门户单例：社团概览静态行 + 关于页元数据。区块正文见 AboutBlock。"""

    title = models.CharField("标题", max_length=200, default="关于我们")
    content = models.TextField("正文（HTML）", blank=True, default="")
    founded = models.CharField("成立", max_length=40, default="2026.03")
    advisor = models.CharField("指导", max_length=80, default="信息组")
    intro = models.CharField("简介", max_length=200, blank=True, default="")
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects = SingletonManager()

    class Meta:
        verbose_name = verbose_name_plural = "关于页"
        permissions = [
            ("manage_aboutpage", "可编辑关于页"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # 单例约束：任何写入都落到 pk=1；若已存在则降级为更新，避免 INSERT 主键冲突。
        self.pk = 1
        if self._state.adding and AboutPage.objects.filter(pk=1).exists():
            self._state.adding = False
            kwargs.pop("force_insert", None)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass


class AboutBlock(models.Model):
    """关于页可独立编辑的区块（关于社团 / 关于一中 / … / 校园一览）。"""

    key = models.SlugField("键", max_length=40, unique=True)
    title = models.CharField("标题", max_length=200)
    content = models.TextField("正文（HTML）", blank=True, default="")
    order = models.PositiveSmallIntegerField("排序", default=0)
    panorama_url = models.URLField("校园全景图外链", blank=True, default="")
    document = models.FileField("文档附件", upload_to=about_document_path, blank=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "关于区块"
        verbose_name_plural = "关于区块"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.title} ({self.key})"
