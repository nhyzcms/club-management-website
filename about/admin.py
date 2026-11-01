from django.contrib import admin

from common.rich_text import sanitize_html

from .models import AboutBlock, AboutPage


@admin.register(AboutPage)
class AboutPageAdmin(admin.ModelAdmin):
    list_display = ("title", "founded", "advisor", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AboutBlock)
class AboutBlockAdmin(admin.ModelAdmin):
    list_display = ("order", "key", "title", "updated_at")
    list_display_links = ("key", "title")
    ordering = ("order",)

    def save_model(self, request, obj, form, change):
        obj.content = sanitize_html(obj.content or "")
        super().save_model(request, obj, form, change)
