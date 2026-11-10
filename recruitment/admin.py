from django.contrib import admin

from common.rich_text import sanitize_html

from .models import RecruitmentNotice


@admin.register(RecruitmentNotice)
class RecruitmentNoticeAdmin(admin.ModelAdmin):
    list_display = ("updated_at",)

    def save_model(self, request, obj, form, change):
        obj.content = sanitize_html(obj.content or "")
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
