"""明信片互寄 · 数据模型（events 形态模块，方案见 docs/plans/postcard-exchange.md）。

所有模型 ``app_label = "events"``（modules 框架约定：新增形态不加 Django app，
迁移集中在 ``events/migrations/``）。模型注册靠 ``events.apps.ready()`` 导入本模块。

归属三轨：登记不强制登录（活动期间任何访客可登记），同一寄出人靠
``device_id``（全站 ``ncdid`` Cookie）+ ``fingerprint_hash``（前端轻量指纹的
SHA-256）+ ``user``（若当时已登录）三轨识别；**修改/查看自己的记录必须出示
6 位登记码**——登记码即防 IDOR 的能力凭证，绝不按自增 id 暴露写入口。
"""
from __future__ import annotations

import os

from django.conf import settings
from django.db import models
from django.utils import timezone

from events.models import Event


def _private_storage():
    """私有文件存储：与公开 MEDIA_ROOT 隔离，只经鉴权视图下发（同身份证明模式）。"""
    from django.core.files.storage import FileSystemStorage

    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def postcard_photo_upload_path(instance, filename):
    """照片落 PRIVATE_MEDIA_ROOT/postcards/<event>/<reg>/<item>-<side>.<ext>。"""
    item = instance.item
    return os.path.join(
        "postcards", str(item.registration.event_id), str(item.registration_id),
        f"{item.pk}-{instance.side}{os.path.splitext(filename)[1].lower()}",
    )


def postcard_announcement_upload_path(instance, filename):
    """公告 PDF 落私有存储（经 CSP:sandbox 视图下发，杜绝 PDF 内嵌 JS 执行）。"""
    return os.path.join("postcards", str(instance.event_id), f"announcement{os.path.splitext(filename)[1].lower()}")


class PostcardConfig(models.Model):
    """明信片互寄活动配置：与 Event 一对一。

    时间轴：``Event.start_at`` = 登记开始、``Event.end_at`` = 活动结束（壳层字段，
    列表/日历直接可用）；本表补 ``ship_at``（寄出节点）与 ``distribute_at``
    （下发节点）两个可空里程碑——空 = 跳过该阶段。阶段推导见 ``state.py``。
    """

    GRADE_CHOICES = [
        ("g1", "高一"),
        ("g2", "高二"),
        ("g3", "高三"),
    ]

    #: 寄达区固定清单（用户 2026-11-08 指定，按此顺序写死）：上海市 16 区，
    #: 拼音序。下拉即按此顺序展示；登记校验与管理端学校配置都以它为准。
    REGION_CHOICES = [
        "浦东新区", "宝山区", "崇明区", "奉贤区", "虹口区", "黄浦区",
        "嘉定区", "金山区", "静安区", "闵行区", "普陀区", "青浦区",
        "松江区", "徐汇区", "杨浦区", "长宁区",
    ]

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="postcard_config", verbose_name="所属活动",
    )
    # 可参与年级：GRADE_CHOICES 的子集（键数组）；空 = 全部三个年级。
    allowed_grades = models.JSONField("可参与年级", default=list, blank=True)
    # 寄达校清单：[{"region": "浦东新区", "name": "××中学"}, ...]；登记表单的
    # 寄达区下拉 = 上面写死的 REGION_CHOICES（固定顺序），寄达校下拉按所选区
    # 从本清单过滤。
    destination_schools = models.JSONField("寄达校清单", default=list, blank=True)
    ship_at = models.DateTimeField("寄出节点", null=True, blank=True)
    distribute_at = models.DateTimeField("下发节点", null=True, blank=True)
    # 公告正文：模块自有字段（活动期间可随时编辑——进度/公告更新是刚需，
    # 不受 Event 壳「开始后锁定」约束）。写入前经 common.rich_text.sanitize_html
    # 白名单净化（word 导入由前端 mammoth 转 HTML 后同样走这道闸）。
    announcement_body = models.TextField("公告正文（HTML，已净化）", blank=True, default="")
    # 公告 PDF（可选，同样活动期间可换）。存私有存储，经 CSP:sandbox 视图下发。
    announcement_pdf = models.FileField(
        "公告 PDF", upload_to=postcard_announcement_upload_path, storage=_private_storage,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "events"
        verbose_name = "明信片互寄配置"
        verbose_name_plural = "明信片互寄配置"
        permissions = [
            ("manage_postcard", "可管理明信片互寄（配置/条码/记录/导出/统计）"),
            ("review_postcard", "可复核与签收明信片"),
        ]

    def __str__(self):
        return f"明信片互寄配置（活动 #{self.event_id}）"

    @property
    def grade_labels(self) -> list[str]:
        labels = dict(self.GRADE_CHOICES)
        keys = self.allowed_grades or [k for k, _ in self.GRADE_CHOICES]
        return [labels[k] for k in keys if k in labels]

    def regions(self) -> list[str]:
        """寄达区下拉数据：固定 16 区清单（REGION_CHOICES，写死顺序）。"""
        return list(self.REGION_CHOICES)


class PostcardBarcode(models.Model):
    """明信片条码：7 位随机数字，Code128 编码，单活动内唯一（跨活动可复用）。

    管理员提前批量生成（1500~10000、步进 500、默认 6000），整版 A4 PDF 导出
    （40×20mm、2mm 裁切间隙）后贴/印在明信片上。登记时用户扫码录入，签收时
    管理员扫码定位——一条码一明信片，绑定关系由 ``PostcardItem`` 的 OneToOne
    收口。
    """

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="postcard_barcodes", verbose_name="所属活动",
    )
    code = models.CharField("条码号", max_length=7, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "events"
        verbose_name = "明信片条码"
        verbose_name_plural = "明信片条码"
        constraints = [
            models.UniqueConstraint(fields=["event", "code"], name="postcard_barcode_unique_per_event"),
        ]
        indexes = [models.Index(fields=["event"], name="postcard_barcode_event_idx")]

    def __str__(self):
        return self.code


class PostcardRegistration(models.Model):
    """一次登记：一名寄出人在一个时刻提交的一束明信片（1~5 张）。

    ``reg_code`` 6 位随机登记码是**唯一识别本次登记的凭证**（弹窗提醒用户保存），
    也是用户事后查看/修改自己记录的口令——接口按 (event, reg_code) 定位，
    绝不暴露自增 id 写入口。
    """

    STATUS_REGISTERED = "registered"
    STATUS_REPORTED = "reported"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_REGISTERED, "已登记"),
        (STATUS_REPORTED, "已报寄"),
        (STATUS_CANCELLED, "已取消"),
    ]

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="postcard_registrations", verbose_name="所属活动",
    )
    reg_code = models.CharField("登记码", max_length=6, db_index=True)
    sender_name = models.CharField("寄出人姓名", max_length=64)
    grade = models.CharField("年级", max_length=2, choices=PostcardConfig.GRADE_CHOICES)
    class_no = models.PositiveSmallIntegerField("班级")
    dest_region = models.CharField("寄达区", max_length=64)
    dest_school = models.CharField("寄达校", max_length=128)
    status = models.CharField("状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_REGISTERED)
    # 归属三轨（见模块 docstring）。
    device_id = models.CharField("设备标识", max_length=40, blank=True, default="", db_index=True)
    fingerprint_hash = models.CharField("指纹哈希", max_length=64, blank=True, default="", db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="postcard_registrations", verbose_name="登记时登录用户",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "events"
        verbose_name = "明信片登记"
        verbose_name_plural = "明信片登记"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "reg_code"], name="postcard_regcode_unique_per_event"),
        ]
        indexes = [
            models.Index(fields=["event", "status"], name="postcard_reg_status_idx"),
            models.Index(fields=["event", "sender_name"], name="postcard_reg_name_idx"),
        ]

    def __str__(self):
        return f"{self.sender_name}·{self.reg_code}"

    @property
    def grade_label(self) -> str:
        return dict(PostcardConfig.GRADE_CHOICES).get(self.grade, self.grade)

    def sync_status_from_items(self):
        """按条目联动登记单状态：全部已报寄 → 已报寄；否则维持已登记。

        取消不联动（管理员可单独取消某张或整单）。原子 update 防并发翻车。
        """
        if self.status == self.STATUS_CANCELLED:
            return
        has_items = self.items.exists()
        all_reported = has_items and not self.items.exclude(
            status=PostcardItem.STATUS_REPORTED
        ).exists()
        target = self.STATUS_REPORTED if all_reported else self.STATUS_REGISTERED
        if target != self.status:
            PostcardRegistration.objects.filter(pk=self.pk).update(
                status=target, updated_at=timezone.now(),
            )
            self.status = target


class PostcardItem(models.Model):
    """登记单内的一张明信片：绑定一个条码（OneToOne → 一条码一明信片）。"""

    STATUS_REGISTERED = "registered"
    STATUS_REPORTED = "reported"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = PostcardRegistration.STATUS_CHOICES

    registration = models.ForeignKey(
        PostcardRegistration, on_delete=models.CASCADE, related_name="items", verbose_name="所属登记",
    )
    barcode = models.OneToOneField(
        PostcardBarcode, on_delete=models.PROTECT, related_name="item", verbose_name="条码",
    )
    status = models.CharField("状态", max_length=12, choices=STATUS_CHOICES, default=STATUS_REGISTERED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "events"
        verbose_name = "明信片条目"
        verbose_name_plural = "明信片条目"
        indexes = [models.Index(fields=["registration"], name="postcard_item_reg_idx")]

    def __str__(self):
        return f"{self.barcode.code}（{self.get_status_display()}）"  # type: ignore[attr-defined]


class PostcardPhoto(models.Model):
    """明信片正/反面照片：私有存储 + 审核状态机。

    生命周期（方案 §7）：AI/人工通过 → 立即删；复核失败 → 用户关标签页
    sendBeacon 删 + TTL 兜底；活动结束 → 全量清除。登记数据永久保留，
    照片行删除不影响登记记录。
    """

    SIDE_FRONT = "front"
    SIDE_BACK = "back"
    SIDE_CHOICES = [(SIDE_FRONT, "正面"), (SIDE_BACK, "反面")]

    REVIEW_PENDING = "pending"            # 待 AI（PR1：登记即过，PR2 起 AI 审）
    REVIEW_AI_PASSED = "ai_passed"
    REVIEW_AI_FAILED = "ai_failed"        # AI 判不匹配（用户可申请人工复核）
    REVIEW_MANUAL_PENDING = "manual_pending"
    REVIEW_MANUAL_PASSED = "manual_passed"
    REVIEW_MANUAL_FAILED = "manual_failed"
    REVIEW_CHOICES = [
        (REVIEW_PENDING, "待审核"),
        (REVIEW_AI_PASSED, "AI 通过"),
        (REVIEW_AI_FAILED, "AI 不匹配"),
        (REVIEW_MANUAL_PENDING, "待人工复核"),
        (REVIEW_MANUAL_PASSED, "人工通过"),
        (REVIEW_MANUAL_FAILED, "人工不通过"),
    ]

    item = models.ForeignKey(
        PostcardItem, on_delete=models.CASCADE, related_name="photos", verbose_name="所属条目",
    )
    side = models.CharField("面", max_length=5, choices=SIDE_CHOICES)
    file = models.FileField("照片", upload_to=postcard_photo_upload_path, storage=_private_storage)
    review_state = models.CharField("审核状态", max_length=16, choices=REVIEW_CHOICES, default=REVIEW_PENDING)
    ai_verdict = models.JSONField("AI 判定详情", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "events"
        verbose_name = "明信片照片"
        verbose_name_plural = "明信片照片"
        constraints = [
            models.UniqueConstraint(fields=["item", "side"], name="postcard_photo_side_unique"),
        ]

    def __str__(self):
        return f"{self.item_id}-{self.side}"

    def delete_file(self):
        """只删物理文件（行保留与否由调用方决定）；失败静默——清理不该拖垮主流程。"""
        try:
            if self.file and self.file.storage.exists(self.file.name):
                self.file.storage.delete(self.file.name)
        except Exception:  # noqa: BLE001
            pass


class PostcardSuggestion(models.Model):
    """活动建议箱：任何访客可提（限流 + Turnstile），管理员后台可读。"""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="postcard_suggestions", verbose_name="所属活动",
    )
    content = models.TextField("建议内容", max_length=1000)
    contact = models.CharField("联系方式（可选）", max_length=128, blank=True, default="")
    device_id = models.CharField("设备标识", max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "events"
        verbose_name = "明信片活动建议"
        verbose_name_plural = "明信片活动建议"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"建议 #{self.pk}"


class PostcardAuditLog(models.Model):
    """管理员操作审计：配置变更 / 条码生成 / 导出 / 记录修改删除 / 签收 / 复核。"""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="postcard_audit_logs", verbose_name="所属活动",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="postcard_audit_logs", verbose_name="操作者",
    )
    action = models.CharField("动作", max_length=32)
    target = models.CharField("对象", max_length=256, blank=True, default="")
    detail = models.JSONField("详情", null=True, blank=True)
    ip = models.GenericIPAddressField("来源 IP", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "events"
        verbose_name = "明信片审计日志"
        verbose_name_plural = "明信片审计日志"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.action}·{self.target}"
