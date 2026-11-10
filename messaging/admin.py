from django.contrib import admin

from .models import (
    Banner,
    Comment,
    CommentThread,
    Conversation,
    Message,
    MessageReadStatus,
    Notification,
)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ["sender", "content", "retracted_at", "created_at"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "created_at", "updated_at"]
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "conversation", "sender", "content_preview", "retracted_at", "created_at"]
    search_fields = ["content"]

    def content_preview(self, obj):
        return obj.content[:50]


@admin.register(MessageReadStatus)
class MessageReadStatusAdmin(admin.ModelAdmin):
    list_display = ["message", "user", "read_at"]


@admin.register(CommentThread)
class CommentThreadAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "target"]
    list_filter = ["status"]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["id", "thread", "author", "content_preview", "retracted_at", "deleted_at", "created_at"]
    search_fields = ["content"]
    list_filter = ["retracted_at", "deleted_at"]

    def content_preview(self, obj):
        return obj.content[:50]


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ["id", "body_preview", "link", "starts_at", "ends_at", "priority", "created_at"]
    list_filter = ["starts_at", "ends_at"]
    ordering = ["-priority", "-created_at"]

    def body_preview(self, obj):
        return obj.body[:50]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:  # 新建公告 → 全员广播（订阅与静默规则照常生效）
            from messaging.services import notify_all

            notify_all(
                "announcement",
                "published",
                payload={
                    "type": "banner",
                    "id": obj.pk,
                    "url": obj.link or "/",
                },
            )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "recipient", "category", "event", "read_at", "created_at"]
    list_filter = ["category", "read_at"]
    search_fields = ["recipient__username", "event"]
    readonly_fields = [
        "recipient", "category", "event", "payload", "read_at", "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
