from django.contrib import admin

from .lifecycle import CANCEL, apply
from .models import Task, TaskClaimRequest

# Tag 的 admin 注册已随模型移到 common/admin.py（B7）。


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "priority", "creator", "assignee", "created_at"]
    list_filter = ["status", "priority"]
    search_fields = ["title", "description"]
    readonly_fields = ["created_at", "updated_at", "completed_at"]
    filter_horizontal = ["tags", "collaborators"]
    actions = ["archive_selected"]

    @admin.action(description="归档")
    def archive_selected(self, request, queryset):
        """批量归档：非终态任务走取消（cancelled）。已完成 / 已取消跳过。"""
        ok = skip = 0
        for task in queryset:
            result = apply(CANCEL, task, request.user)
            if result.ok:
                ok += 1
            else:
                skip += 1
        self.message_user(request, f"已归档 {ok} 个任务。跳过 {skip} 个。")


@admin.register(TaskClaimRequest)
class TaskClaimRequestAdmin(admin.ModelAdmin):
    list_display = ["task", "claimant", "status", "moderated_by", "created_at"]
    list_filter = ["status"]
