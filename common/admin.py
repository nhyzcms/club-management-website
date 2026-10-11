from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Singleton admin: one row, no add/delete, changelist jumps to the form."""

    fieldsets = (
        (
            "验证",
            {
                "fields": (
                    "verification_enabled",
                    "verification_valid_days",
                    "admin_valid_days",
                    "registration_verify_days",
                )
            },
        ),
        ("审核", {"fields": ("content_review_enabled",)}),
        ("评论", {"fields": ("comments_enabled", "comment_max_depth")}),
        ("私信", {"fields": ("dms_enabled",)}),
        (
            "注册与限流",
            {
                "fields": (
                    "registration_enabled",
                    "register_per_ip_per_day",
                    "resend_verification_per_ip_per_hour",
                    "login_per_ip_per_hour",
                    "login_per_username_per_hour",
                    "feedback_anon_per_ip_per_day",
                    "reports_per_user_per_day",
                    "authcode_redeem_per_user_per_hour",
                )
            },
        ),
        ("上传", {"fields": ("sync_upload_max_bytes", "tus_media_max_bytes")}),
        (
            "自动更新",
            {
                "fields": (
                    "auto_update_enabled",
                    "update_poll_interval_seconds",
                    "update_timezone",
                    "update_window_start_hour",
                    "update_window_end_hour",
                    "update_apply_cutoff_minutes_before_end",
                    "update_release_keep",
                    "update_db_backup_keep",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        return HttpResponseRedirect(
            reverse("admin:common_sitesettings_change", args=[obj.pk])
        )
