from django.contrib import admin, messages

from common.rich_text import sanitize_html

from .models import News


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ["title", "author", "featured", "is_published", "views", "published_at"]
    list_filter = ["featured", "is_published"]
    search_fields = ["title", "summary", "content"]
    readonly_fields = ["views", "published_at", "created_at", "updated_at"]
    filter_horizontal = ["tags"]
    date_hierarchy = "published_at"
    actions = ["archive_selected"]

    def save_model(self, request, obj, form, change):
        # admin 写路径也要过与 API 相同的净化器（审计 L-9）：否则有 change_news 的
        # staff 可在待审稿里放 <img onerror>，审核员预览即执行。
        obj.content = sanitize_html(obj.content or "")
        super().save_model(request, obj, form, change)

    @admin.action(description="归档")
    def archive_selected(self, request, queryset):
        """批量归档：已发布 → 取消发布（不对公众展示）。"""
        if not request.user.has_perm("news.manage_news"):
            self.message_user(request, "没有归档权限。", level=messages.ERROR)
            return
        ok = queryset.filter(is_published=True).update(is_published=False)
        skip = queryset.count() - ok
        self.message_user(request, f"已归档 {ok} 条新闻。跳过 {skip} 条。")
