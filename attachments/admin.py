from django.contrib import admin

from .models import Attachment


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "file_name", "file_type", "uploaded_by", "target", "uploaded_at")
    list_filter = ("file_type",)
    search_fields = ("file_name",)
    readonly_fields = ("uploaded_at", "file_size", "file_type")
