"""统一审核：正交于对象自身生命周期，只门控公开可见性。

一条 Review 恰好挂一个父级（新闻 / 活动 / 教程）。
状态机见 lifecycle.py；此处只给字段与约束。
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from common.targets import TargetBackfillMixin


class Review(TargetBackfillMixin, models.Model):
    """审核记录：待审 → 通过 / 驳回，通过后可下架。"""

    # B1：双写期把旧列折射到 target（B9 删旧列时一并移除）。
    TARGET_LEGACY_FIELDS = {"news": "news", "activity": "activity", "tutorial": "tutorial"}

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_REMOVED = "removed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待审"),
        (STATUS_APPROVED, "通过"),
        (STATUS_REJECTED, "驳回"),
        (STATUS_REMOVED, "下架"),
    ]

    status = models.CharField("状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # B2：审计三件套统一命名（moderated_by / moderated_at / moderation_note）。
    # 原为 reviewer / reviewed_at / comment——六张表曾用五套不同的名字指同一组概念。
    moderation_note = models.TextField("评语", blank=True, default="")
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="moderated_reviews", verbose_name="审核人",
    )
    moderated_at = models.DateTimeField("审核时间", null=True, blank=True)

    news = models.OneToOneField(
        "news.News", on_delete=models.CASCADE,
        null=True, blank=True, related_name="review", verbose_name="新闻",
    )
    activity = models.OneToOneField(
        "activities.Activity", on_delete=models.CASCADE,
        null=True, blank=True, related_name="publication_review", verbose_name="活动",
    )
    tutorial = models.OneToOneField(
        "tutorials.Tutorial", on_delete=models.CASCADE,
        null=True, blank=True, related_name="review", verbose_name="教程",
    )
    # B1：统一宿主锚点（双写期，B9 删上面三个旧列）。
    target = models.OneToOneField(
        "common.ContentTarget", on_delete=models.CASCADE,
        null=True, blank=True, related_name="review", verbose_name="内容目标",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "审核"
        verbose_name_plural = "审核"
        ordering = ["-created_at"]
        permissions = [
            ("force_publish", "可免审发布"),
            ("moderate", "可审核内容"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(news__isnull=False, activity__isnull=True, tutorial__isnull=True)
                    | models.Q(news__isnull=True, activity__isnull=False, tutorial__isnull=True)
                    | models.Q(news__isnull=True, activity__isnull=True, tutorial__isnull=False)
                ),
                name="review_exactly_one_parent",
            ),
        ]

    def __str__(self):
        target = self.news or self.activity or self.tutorial
        return f"{self.get_status_display()}:{target}"


class Feedback(models.Model):
    """意见反馈：无对象投递箱。待处理 → 已了结。"""

    CATEGORY_SUGGESTION = "suggestion"
    CATEGORY_COMPLAINT = "complaint"
    CATEGORY_OTHER = "other"
    CATEGORY_CHOICES = [
        (CATEGORY_SUGGESTION, "建议"),
        (CATEGORY_COMPLAINT, "投诉"),
        (CATEGORY_OTHER, "其他"),
    ]

    STATUS_PENDING = "pending"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待处理"),
        (STATUS_CLOSED, "已了结"),
    ]

    category = models.CharField("类别", max_length=20, choices=CATEGORY_CHOICES)
    status = models.CharField("状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    title = models.CharField("标题", max_length=200)
    description = models.TextField("详细说明", blank=True, default="")
    contact = models.CharField("联系方式（选填）", max_length=100, blank=True, default="")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="created_feedbacks", verbose_name="创建人",
    )
    # B2：审计三件套（原 closed_by / closed_at / close_note）
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="closed_feedbacks", verbose_name="了结人",
    )
    moderated_at = models.DateTimeField("了结时间", null=True, blank=True)
    moderation_note = models.TextField("了结说明", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "意见反馈"
        verbose_name_plural = "意见反馈"
        ordering = ["-created_at"]
        default_permissions = ("add", "change", "delete")
        permissions = [
            ("read_feedback", "可查看并了结意见反馈"),
        ]

    def __str__(self):
        return f"{self.get_category_display()}: {self.title}"


class ReportCase(TargetBackfillMixin, models.Model):
    """举报案：有对象的调查票。进行中 → 驳回 / 成立并处置。"""

    # B1：双写期把旧内容列折射到 target。reported_user 不在此列——「人」不是内容。
    TARGET_LEGACY_FIELDS = {
        "news": "news",
        "activity": "activity",
        "tutorial": "tutorial",
        "comment": "comment",
    }

    STATUS_OPEN = "open"
    STATUS_DISMISSED = "dismissed"
    STATUS_UPHELD = "upheld"
    STATUS_CHOICES = [
        (STATUS_OPEN, "进行中"),
        (STATUS_DISMISSED, "驳回"),
        (STATUS_UPHELD, "成立并处置"),
    ]

    status = models.CharField("状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN)
    news = models.ForeignKey(
        "news.News", on_delete=models.CASCADE,
        null=True, blank=True, related_name="report_cases", verbose_name="新闻",
    )
    activity = models.ForeignKey(
        "activities.Activity", on_delete=models.CASCADE,
        null=True, blank=True, related_name="report_cases", verbose_name="活动",
    )
    tutorial = models.ForeignKey(
        "tutorials.Tutorial", on_delete=models.CASCADE,
        null=True, blank=True, related_name="report_cases", verbose_name="教程",
    )
    comment = models.ForeignKey(
        "messaging.Comment", on_delete=models.CASCADE,
        null=True, blank=True, related_name="report_cases", verbose_name="评论",
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="report_cases_against", verbose_name="被举报用户",
    )
    # B1：统一宿主锚点（双写期）。**被举报用户不进 target**——「人」不是「内容」，
    # 语义不同，且用户删除后举报案应留档。所以 reported_user 保持独立列。
    target = models.ForeignKey(
        "common.ContentTarget", on_delete=models.CASCADE,
        null=True, blank=True, related_name="report_cases", verbose_name="内容目标",
    )
    # B2：审计三件套（原 resolved_by / resolved_at / resolution_comment）
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="resolved_report_cases", verbose_name="处理人",
    )
    moderated_at = models.DateTimeField("处理时间", null=True, blank=True)
    moderation_note = models.TextField("处理说明", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "举报案"
        verbose_name_plural = "举报案"
        ordering = ["-created_at"]
        permissions = [
            ("handle_report", "可处理举报案"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        news__isnull=False, activity__isnull=True, tutorial__isnull=True,
                        comment__isnull=True, reported_user__isnull=True,
                    )
                    | models.Q(
                        news__isnull=True, activity__isnull=False, tutorial__isnull=True,
                        comment__isnull=True, reported_user__isnull=True,
                    )
                    | models.Q(
                        news__isnull=True, activity__isnull=True, tutorial__isnull=False,
                        comment__isnull=True, reported_user__isnull=True,
                    )
                    | models.Q(
                        news__isnull=True, activity__isnull=True, tutorial__isnull=True,
                        comment__isnull=False, reported_user__isnull=True,
                    )
                    | models.Q(
                        news__isnull=True, activity__isnull=True, tutorial__isnull=True,
                        comment__isnull=True, reported_user__isnull=False,
                    )
                ),
                name="reportcase_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["news"],
                condition=models.Q(status="open", news__isnull=False),
                name="one_open_report_per_news",
            ),
            models.UniqueConstraint(
                fields=["activity"],
                condition=models.Q(status="open", activity__isnull=False),
                name="one_open_report_per_activity",
            ),
            models.UniqueConstraint(
                fields=["tutorial"],
                condition=models.Q(status="open", tutorial__isnull=False),
                name="one_open_report_per_tutorial",
            ),
            models.UniqueConstraint(
                fields=["comment"],
                condition=models.Q(status="open", comment__isnull=False),
                name="one_open_report_per_comment",
            ),
            models.UniqueConstraint(
                fields=["reported_user"],
                condition=models.Q(status="open", reported_user__isnull=False),
                name="one_open_report_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.get_status_display()}:{self.pk}"


class ReportFiling(models.Model):
    """一份举报：挂在某张举报案上，每举报人每案至多一份。"""

    case = models.ForeignKey(
        ReportCase, on_delete=models.CASCADE,
        related_name="filings", verbose_name="举报案",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="report_filings", verbose_name="举报人",
    )
    reason = models.TextField("理由")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "举报"
        verbose_name_plural = "举报"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["case", "reporter"], name="one_filing_per_reporter_per_case"),
        ]

    def __str__(self):
        return f"filing:{self.case_id}:{self.reporter_id}"


class UserMute(models.Model):
    """全站禁言（纪律处罚）。归属审核模块；表名沿用 messaging 时期（数据零迁移）。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="mutes", verbose_name="被禁言用户",
    )
    muted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="issued_mutes", verbose_name="操作人",
    )
    reason = models.TextField("理由", blank=True, default="")
    starts_at = models.DateTimeField("开始时间", default=timezone.now)
    ends_at = models.DateTimeField("结束时间", null=True, blank=True)
    lifted_at = models.DateTimeField("解除时间", null=True, blank=True)

    class Meta:
        db_table = "messaging_usermute"
        verbose_name = "禁言"
        verbose_name_plural = "禁言"
        ordering = ["-starts_at"]
        permissions = [
            ("mute_user", "全站禁言"),
        ]
        indexes = [
            models.Index(fields=["user", "lifted_at", "ends_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} muted by {self.muted_by.username}"
