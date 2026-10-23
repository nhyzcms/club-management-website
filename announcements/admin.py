"""后台：发布全站弹窗公告 + 看已读情况。

发布动作在 ``save_model`` 里做（状态改为「已发布」且 ``published_at`` 为空时触发一次），
幂等由 ``services.publish`` 保证：再点保存不会给全员发第二遍。
"""
from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    MAX_DOCUMENT_BYTES,
    Announcement,
    AnnouncementRead,
    document_kind_of,
)
from .services import publish, recipient_queryset, stats


class AnnouncementAdminForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = "__all__"

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if not document:
            return document
        size = getattr(document, "size", 0) or 0
        if size > MAX_DOCUMENT_BYTES:
            raise forms.ValidationError(
                f"文档不能超过 {MAX_DOCUMENT_BYTES // (1024 * 1024)}MB"
            )
        # 未重传时 document 是已存的 FieldFile，扩展名已校验过，直接放行。
        if getattr(document, "_committed", True):
            return document
        if not document_kind_of(
            getattr(document, "name", ""), getattr(document, "content_type", ""),
        ):
            raise forms.ValidationError("仅支持 PDF 或 .docx（其他格式无法保真渲染）")
        return document

    def clean(self):
        data = super().clean()
        status = data.get("status")
        expires_at = data.get("expires_at")
        if (
            status == Announcement.STATUS_PUBLISHED
            and expires_at is not None
            and expires_at <= timezone.now()
        ):
            raise forms.ValidationError({"expires_at": "下线时间已过，发布后不会弹出。"})
        return data


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    form = AnnouncementAdminForm
    list_display = [
        "id", "title", "audience", "status", "send_email",
        "published_at", "expires_at", "read_count", "created_at",
    ]
    list_filter = ["status", "audience", "send_email"]
    search_fields = ["title", "summary"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
    readonly_fields = [
        "published_at", "document_name", "document_kind", "document_size",
        "created_by", "created_at", "updated_at", "stats_panel",
    ]
    fieldsets = [
        (None, {
            "fields": ["title", "summary"],
            "description": "正文可以留空（例如只有一张通知扫描件）。",
        }),
        ("文档（可选，按原排版渲染）", {
            "fields": ["document", "document_name", "document_kind", "document_size"],
        }),
        ("发布范围与渠道", {
            "fields": ["audience", "send_email", "status", "expires_at", "published_at"],
            "description": (
                "保存时若状态为「已发布」且尚未发布过，会立刻向受众推送站内通知"
                "（可选再加一封邮件）。发布时间由系统在首次发布时写入。"
            ),
        }),
        ("统计", {"fields": ["stats_panel"]}),
        ("记录", {"fields": ["created_by", "created_at", "updated_at"]}),
    ]
    actions = ["action_publish", "action_unpublish"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_read_count=Count("reads", distinct=True))

    # ---- 权限：模块整体由命名工作流权限收口（见 migrations/0002）----
    def _can_manage(self, request) -> bool:
        return request.user.has_perm("announcements.manage_announcements")

    def has_module_permission(self, request):
        return self._can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self._can_manage(request)

    def has_add_permission(self, request):
        return self._can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self._can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self._can_manage(request)

    # ---- 列 -------------------------------------------------------------
    @admin.display(description="已读", ordering="_read_count")
    def read_count(self, obj):
        return obj._read_count

    @admin.display(description="统计")
    def stats_panel(self, obj):
        if obj.pk is None:
            return "保存后可查看。"
        data = stats(obj)
        url = reverse("admin:announcements_announcement_reads", args=[obj.pk])
        # 比率先格式化成字符串：format_html 会把所有参数转成 SafeString，
        # 直接写 {:.1f} 会报 "Unknown format code 'f' for object of type 'SafeString'"。
        rate = f"{data['read_rate']:.1f}"
        return format_html(
            "受众 <b>{}</b> 人 · 已读 <b>{}</b> 人（{}%）· 未读 <b>{}</b> 人"
            " · 邮件 入队 {} / 已送达 {}"
            '<div style="margin-top:6px"><a class="button" href="{}">查看已读明细</a></div>',
            data["recipients"], data["read_count"], rate,
            data["unread_count"], data["email_queued"], data["email_sent"], url,
        )

    def save_model(self, request, obj, form, change):
        document = form.cleaned_data.get("document")
        if document and not getattr(document, "_committed", True):
            obj.document_name = (getattr(document, "name", "") or "")[:255]
            obj.document_kind = document_kind_of(
                getattr(document, "name", ""), getattr(document, "content_type", ""),
            )
            obj.document_size = getattr(document, "size", 0) or 0
        elif not obj.document:
            obj.document_name = ""
            obj.document_kind = ""
            obj.document_size = 0
        if obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

        if obj.status == Announcement.STATUS_PUBLISHED:
            result = publish(obj, actor=request.user)
            if not result.get("already_published"):
                email_note = (
                    f"邮件入队 {result['emails']} 封" if obj.send_email else "不发送邮件"
                )
                self.message_user(
                    request,
                    f"已发布：站内通知 {result['notified']} 人，{email_note}。",
                    messages.SUCCESS,
                )

    # ---- 批量动作 -------------------------------------------------------
    @admin.action(description="发布所选公告（推送给受众）")
    def action_publish(self, request, queryset):
        published = 0
        for row in queryset:
            if row.published_at is None:
                publish(row, actor=request.user)
                published += 1
        self.message_user(request, f"已发布 {published} 条公告。", messages.SUCCESS)

    @admin.action(description="下线所选公告（停止弹窗，站内通知保留）")
    def action_unpublish(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(status=Announcement.STATUS_ARCHIVED, updated_at=now)
        self.message_user(request, f"已下线 {updated} 条公告。", messages.SUCCESS)

    # ---- 已读明细 -------------------------------------------------------
    def get_urls(self):
        custom = [
            path(
                "<int:object_id>/reads/",
                self.admin_site.admin_view(self.reads_view),
                name="announcements_announcement_reads",
            ),
        ]
        return custom + super().get_urls()

    def reads_view(self, request, object_id: int):
        if not self._can_manage(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        announcement = self.get_object(request, object_id)
        if announcement is None:
            from django.http import Http404

            raise Http404("公告不存在")
        read_rows = dict(
            announcement.reads.select_related("user").values_list("user_id", "read_at")
        )
        rows = [
            {
                "user": user,
                "read_at": read_rows.get(user.pk),
                "nickname": getattr(getattr(user, "profile", None), "nickname", "") or "",
            }
            for user in recipient_queryset(announcement.audience).order_by("id")
        ]
        rows.sort(key=lambda row: (row["read_at"] is None, -row["user"].pk))
        context = {
            **self.admin_site.each_context(request),
            "title": f"已读明细 · {announcement.title}",
            "announcement": announcement,
            "rows": rows,
            "stats": stats(announcement),
            "opts": self.model._meta,
            "read_count": len(read_rows),
            "total": len(rows),
        }
        return TemplateResponse(
            request,
            "admin/announcements/announcement/reads.html",
            context,
        )


@admin.register(AnnouncementRead)
class AnnouncementReadAdmin(admin.ModelAdmin):
    """只读审计表（日常看已读请用公告页的「查看已读明细」，那里带未读名单）。"""

    list_display = ["id", "announcement", "user", "read_at"]
    list_filter = ["announcement"]
    search_fields = ["user__username", "announcement__title"]
    readonly_fields = ["announcement", "user", "read_at"]

    def has_module_permission(self, request):
        return request.user.has_perm("announcements.manage_announcements")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("announcements.manage_announcements")

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm("announcements.manage_announcements")
