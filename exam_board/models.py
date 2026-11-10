import uuid

from django.conf import settings
from django.db import models

from common.uploads import safe_extension


def errata_upload_path(instance, filename):
    ext = safe_extension(filename)
    return f"exam_errata/{uuid.uuid4().hex}{ext}"


class Exam(models.Model):
    """一场考试：由若干批次组成。看板按批次展示科目与时间。"""

    title = models.CharField("考试标题", max_length=50)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="exam_records", verbose_name="写入人",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "考试"
        verbose_name_plural = "考试"
        ordering = ["-id"]
        permissions = [
            ("manage_exams", "可管理考试看板"),
        ]

    def __str__(self):
        return self.title


class ExamBatch(models.Model):
    """考试批次：同一场考试下的一条课表（如高一 / 高二）。"""

    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, related_name="batches", verbose_name="考试",
    )
    name = models.CharField("批次名称", max_length=50)
    sort_order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        verbose_name = "考试批次"
        verbose_name_plural = "考试批次"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["exam", "name"], name="exam_batch_unique_name"),
        ]

    def __str__(self):
        return f"{self.exam.title} · {self.name}"


class ExamSubject(models.Model):
    """科目场次：某日某时段的一场科目；同一批次内场次之间的间隙即为休息。"""

    batch = models.ForeignKey(
        ExamBatch, on_delete=models.CASCADE, related_name="subjects", verbose_name="批次",
    )
    name = models.CharField("科目", max_length=30)
    exam_date = models.DateField("考试日期")
    start_time = models.TimeField("开始时间")
    end_time = models.TimeField("结束时间")
    sort_order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        verbose_name = "科目场次"
        verbose_name_plural = "科目场次"
        ordering = ["exam_date", "start_time", "sort_order", "id"]

    def __str__(self):
        return f"{self.batch} {self.exam_date} {self.name}"


class ExamErrata(models.Model):
    """题目误刊：一场考试上的图文更正；可同时多条，本场结束按发布顺序依次失效。"""

    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, related_name="errata",
        null=True, blank=True, verbose_name="考试",
    )
    text = models.CharField("说明", max_length=500, blank=True)
    image = models.ImageField("图片", upload_to=errata_upload_path, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="exam_errata", verbose_name="发布人",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField("到期（本场结束）", null=True, blank=True)
    dismissed_at = models.DateTimeField("撤回时间", null=True, blank=True)

    class Meta:
        verbose_name = "题目误刊"
        verbose_name_plural = "题目误刊"
        ordering = ["id"]

    def __str__(self):
        return self.text[:40] or f"误刊 #{self.pk}"
