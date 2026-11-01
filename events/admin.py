"""活动后台：草稿/时间窗/状态一览；发布与归档走 API 动作，后台只做数据修正。"""
from django.contrib import admin

from .models import Event


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
