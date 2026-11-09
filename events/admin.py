"""活动后台：草稿/时间窗/状态一览；发布与归档走 API 动作，后台只做数据修正。

``PostcardSeasonAdmin`` 是明信片互寄的年度（批次）管理页：只读一览 + 一键删除
整届活动的全部数据（用户 2026-11-09 要求）。
"""
from django.contrib import admin, messages
from django.db.models import Count

from .models import Event
from .modules.postcard import lifecycle as postcard_lifecycle
from .modules.postcard.models import PostcardConfig


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = [
        "id", "title", "status", "visibility", "module_key",
        "start_at", "end_at", "organizer",
    ]
    list_filter = ["status", "visibility", "module_key"]
    search_fields = ["title", "summary"]
    date_hierarchy = "start_at"
    autocomplete_fields = []
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("title", "summary", "body")}),
        ("时间窗", {"fields": ("start_at", "end_at"), "description": "到 end_at 自动结束；留空则不自动关闭。"}),
        ("运营", {"fields": ("status", "visibility", "module_key", "organizer")}),
        ("记录", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(PostcardConfig)
class PostcardSeasonAdmin(admin.ModelAdmin):
    """明信片互寄 · 年度（批次）管理：只读一览 + 删除整批。

    删除动作走 admin 自带确认页；执行时先清私有存储里的照片 / 样例图 / 公告
    PDF，再删 Event——config / 条码 / 登记 / 条目 / 照片行 / 建议 / 审计全部
    随级联删除，**不可恢复**。日常配置仍走网站管理端，这里只做批次治理。
    """

    list_display = [
        "event_title", "event_status", "start_at", "end_at",
        "registration_total", "barcode_total",
    ]
    list_filter = ["event__status"]
    search_fields = ["event__title"]
    ordering = ["-event__start_at", "-id"]
    actions = ["delete_season"]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("event")
            .annotate(
                registration_total=Count("event__postcard_registrations", distinct=True),
                barcode_total=Count("event__postcard_barcodes", distinct=True),
            )
        )

    @admin.display(description="活动", ordering="event__title")
    def event_title(self, obj):
        return obj.event.title

    @admin.display(description="状态", ordering="event__status")
    def event_status(self, obj):
        return obj.event.get_status_display()

    @admin.display(description="登记单", ordering="registration_total")
    def registration_total(self, obj):
        return obj.registration_total

    @admin.display(description="条码数", ordering="barcode_total")
    def barcode_total(self, obj):
        return obj.barcode_total

    @admin.display(description="登记开始", ordering="event__start_at")
    def start_at(self, obj):
        return obj.event.start_at

    @admin.display(description="结束", ordering="event__end_at")
    def end_at(self, obj):
        return obj.event.end_at

    def has_add_permission(self, request):
        """批次只能由网站「开启新一届」创建，后台不新增，避免造出半截活动。"""
        return False

    def has_change_permission(self, request, obj=None):
        """配置编辑走网站管理端（有壳锁与审计）；后台只读。"""
        return False

    @admin.action(description="删除该年度互寄批次（含全部数据，不可恢复）", permissions=["delete"])
    def delete_season(self, request, queryset):
        for config in queryset.select_related("event"):
            event = config.event
            title = event.title
            stats = postcard_lifecycle.delete_season(event)
            self.message_user(
                request,
                f"已删除「{title}」：照片 {stats['photos']} 张、样例 {stats['samples']} 张、"
                f"公告 PDF {'已删除' if stats['announcement_pdf'] else '无'}；"
                "登记、条码、审计等数据已随活动一并删除。",
                level=messages.WARNING,
            )
