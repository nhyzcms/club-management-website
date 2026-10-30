from django.conf import settings
from django.db import models

# Tag 已移到 ``common``（B7）。这里保留导入路径，让既有
# ``from tasks.models import Tag`` 不必一次性全改；新代码请直接
# ``from common.models import Tag``。物理表仍是 ``tasks_tag``（零 DDL）。
from common.models import Tag  # noqa: F401


class Task(models.Model):
    """任务"""
    STATUS_CHOICES = [
        ("pending", "待处理"),
        ("in_progress", "进行中"),
        ("reviewing", "待验收"),
        ("review", "审核中"),
        ("completed", "已完成"),
        ("cancelled", "已取消"),
    ]
    PRIORITY_CHOICES = [
        ("low", "低"),
        ("medium", "中"),
        ("high", "高"),
        ("urgent", "紧急"),
    ]

    title = models.CharField("标题", max_length=200)
    description = models.TextField("描述", blank=True)
    status = models.CharField("状态", max_length=20, choices=STATUS_CHOICES, default="pending")
    priority = models.CharField("优先级", max_length=20, choices=PRIORITY_CHOICES, default="medium")

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="created_tasks", verbose_name="创建人",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="assigned_tasks", verbose_name="负责人",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="tasks", verbose_name="标签")

    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True,
        related_name="collaborating_tasks", verbose_name="协作者",
    )

    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    reject_reason = models.TextField("打回理由", blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "任务"
        verbose_name_plural = "任务"
        ordering = ["-created_at"]
        permissions = [
            ("manage_tasks", "可管理/审批任意任务"),
            ("assign_task", "可直接指派任务"),
        ]

    def __str__(self):
        return self.title


class TaskClaimRequest(models.Model):
    """任务认领请求"""
    STATUS_CHOICES = [
        ("pending", "待审核"),
        ("approved", "已通过"),
        ("rejected", "已拒绝"),
    ]

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE,
        related_name="claim_requests", verbose_name="任务",
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="claim_requests", verbose_name="申请者",
    )
    status = models.CharField("状态", max_length=10, choices=STATUS_CHOICES, default="pending")
    reason = models.TextField("申请理由", blank=True)
    # B2：审计三件套统一命名（原 reviewed_by / reviewed_at）
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewed_claims", verbose_name="审核人",
    )
    moderated_at = models.DateTimeField("审核时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "认领请求"
        verbose_name_plural = "认领请求"
        ordering = ["-created_at"]
        unique_together = ["task", "claimant"]

    def __str__(self):
        return f"{self.claimant.username} -> {self.task.title} ({self.status})"


# 附件（Attachment）已统一到独立 attachments app：见 attachments/models.py。
# 删除任务时，CASCADE 经统一附件的可空 task 外键连带删除其附件行，再由该 app 的
# post_delete 信号回收磁盘文件——故此处不再需要内嵌附件模型。

