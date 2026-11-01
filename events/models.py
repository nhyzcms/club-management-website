"""活动模型（2026-10 新增）。

「活动」与 ``activities.Activity``（用户可见名「互动」）是两种东西：

- **互动**：星形结构——中心向成员发起，成员各自交回东西（票 / 作品 / 展品 /
  答卷），参与者之间没有关系；
- **活动**：允许参与者之间发生关系（配对 / 组队 / 互评 / 接力），有明确的起止
  时间窗，大部分限时，到点自动关闭。

本 app 只提供活动的**壳**（标题 / 简介 / 正文 / 时间窗 / 状态 / 可见性）与一套
严格的生命周期；具体形态放在 ``events/modules/<key>/``，由 ``module_key`` 指向。
``module_key`` 为空 = 纯展示型活动（公告性质，只有内容与时间窗）。

状态机见 ``lifecycle.py``（遵循 ADR 0003：状态机与访问控制分离，此处只给 DB 枚举）。
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Event(models.Model):
    """活动：一段有明确起止的时间窗，参与方式由 ``module_key`` 决定。"""

    STATUS_DRAFT = "draft"
    STATUS_SCHEDULED = "scheduled"
    STATUS_ACTIVE = "active"
    STATUS_ENDED = "ended"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "草稿"),
        (STATUS_SCHEDULED, "待开始"),
        (STATUS_ACTIVE, "进行中"),
        (STATUS_ENDED, "已结束"),
        (STATUS_ARCHIVED, "已归档"),
    ]

    VISIBILITY_PUBLIC = "public"
    VISIBILITY_MEMBERS = "members"
    VISIBILITY_CHOICES = [
        (VISIBILITY_PUBLIC, "公开"),
        (VISIBILITY_MEMBERS, "仅成员"),
    ]

    title = models.CharField("标题", max_length=200)
    summary = models.CharField("简介", max_length=300, blank=True, default="")
    body = models.TextField("正文（HTML）", blank=True, default="")

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="organized_events", verbose_name="组织者",
    )

    # 时间窗：开始必填；结束可留空（= 暂不设结束，never auto-close）。
    start_at = models.DateTimeField("开始时间")
    end_at = models.DateTimeField("结束时间", null=True, blank=True)

    status = models.CharField(
        "状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT,
    )
    visibility = models.CharField(
        "可见范围", max_length=8, choices=VISIBILITY_CHOICES, default=VISIBILITY_MEMBERS,
    )

    # 活动形态模块键（events/modules/ 下的包名）；留空 = 纯展示型活动。
    # 框架阶段不校验取值——模块清单由 lifecyle 之外的注册表维护，未知键降级为纯展示。
    module_key = models.CharField("形态模块", max_length=40, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "活动"
        verbose_name_plural = "活动"
        ordering = ["-start_at", "-id"]
        permissions = [
            ("manage_events", "可管理任意活动"),
            ("manage_event_types", "可装载 / 卸载活动形态"),
        ]
        indexes = [
            models.Index(fields=["status", "start_at"], name="event_status_start_idx"),
            models.Index(fields=["status", "end_at"], name="event_status_end_idx"),
        ]

    def __str__(self):
        return f"{self.title}（{self.get_status_display()}）"  # type: ignore[attr-defined]

    def clean(self):
        """时间窗自洽：结束不得早于开始（admin / ModelForm 路径的安全网）。"""
        super().clean()
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "结束时间必须晚于开始时间"})

    @property
    def is_open_for_participation(self):
        """此刻是否开放参与（纯读属性，不做流转——调用方先用 lifecycle.touch()）。"""
        return self.status == self.STATUS_ACTIVE
