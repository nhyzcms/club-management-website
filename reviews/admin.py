from django.contrib import admin, messages
from django.utils.html import format_html

from .lifecycle import APPROVE, REJECT, REMOVE, TransitionDenied, apply
from .models import Feedback, ReportCase, Review, UserMute

#: 审核对象的后台预览路径：kind → 前端路由模板。
_TARGET_PREVIEW = {
    "news": "/news/{}",
    "activity": "/activity/{}",
    "tutorial": "/tutorials/{}",
}


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "target", "moderated_by", "moderated_at", "created_at"]
    list_filter = ["status"]
    search_fields = ["moderation_note"]
    readonly_fields = [
        "target", "moderated_by",
        "moderated_at", "created_at", "updated_at", "target_preview",
    ]
    fieldsets = (
        (None, {"fields": ("status", "moderation_note", "moderated_by", "moderated_at")}),
        ("对象", {"fields": ("target",)}),
        ("预览", {"fields": ("target_preview",)}),
    )
    actions = ["approve_selected", "reject_selected", "remove_selected"]

    class Media:
        css = {"all": ["reviews/admin_preview.css"]}

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("reviews.moderate"):
            for name in ("approve_selected", "reject_selected", "remove_selected"):
                actions.pop(name, None)
        return actions

    def _bulk_apply(self, request, queryset, action, *, comment=""):
        if not request.user.has_perm("reviews.moderate"):
            self.message_user(request, "没有审核权限。", level=messages.ERROR)
            return
        ok = skip = 0
        for review in queryset.select_related("target"):
            try:
                apply(action, review, request.user, comment=comment)
                ok += 1
            except TransitionDenied:
                skip += 1
        labels = {APPROVE: "通过", REJECT: "驳回", REMOVE: "下架"}
        self.message_user(request, f"已{labels[action]} {ok} 条。跳过 {skip} 条。")

    @admin.action(description="通过")
    def approve_selected(self, request, queryset):
        self._bulk_apply(request, queryset, APPROVE)

    @admin.action(description="驳回")
    def reject_selected(self, request, queryset):
        self._bulk_apply(request, queryset, REJECT, comment="后台批量驳回")

    @admin.action(description="下架")
    def remove_selected(self, request, queryset):
        self._bulk_apply(request, queryset, REMOVE)

    @admin.display(description="对象界面")
    def target_preview(self, obj):
        if not obj or not obj.pk:
            return "—"
        # B9：Review 只通过 target 锚定对象，没有 news_id / activity_id / tutorial_id
        if obj.target_id is None:
            return "—"
        tmpl = _TARGET_PREVIEW.get(obj.target.kind)
        if tmpl is None:
            return "—"
        path = tmpl.format(obj.target.object_id)
        src = f"/#{path}?embed=1"
        return format_html(
            '<p style="margin:0 0 8px">'
            '<a href="{}" target="_blank" rel="noopener">新标签打开</a></p>'
            '<iframe src="{}" title="对象界面" '
            'style="width:100%;height:80vh;border:1px solid #d0d5dd;'
            'border-radius:8px;background:#fff"></iframe>',
            src,
            src,
        )


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "category", "status", "creator", "moderated_by", "created_at"]
    list_filter = ["status", "category"]
    search_fields = ["title", "description"]
    readonly_fields = ["created_at", "updated_at", "moderated_at"]


@admin.register(ReportCase)
class ReportCaseAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "target", "reported_user", "moderated_by", "created_at"]
    list_filter = ["status"]
    search_fields = ["moderation_note"]
    readonly_fields = ["created_at", "updated_at", "moderated_at"]


@admin.register(UserMute)
class UserMuteAdmin(admin.ModelAdmin):
    """全站禁言（自 messaging 迁入；数据面表名不变）。"""

    list_display = ["id", "user", "muted_by", "starts_at", "ends_at", "lifted_at"]
    list_filter = ["starts_at", "ends_at", "lifted_at"]
    search_fields = ["user__username", "reason"]
