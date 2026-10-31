from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html

from common.surveyjs_admin import SurveyJSAdminMixin, SurveyJSResponseViewMixin

from . import survey_export
from .lifecycle import archive, can_edit_schema
from .models import (
    Activity, Ballot, BallotSelection, Questionnaire, QuestionnaireResponse,
    Submission, VoteOption,
)


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = [
        "title", "type", "status", "audience", "questionnaire_link",
        "creator", "end_at", "is_permanent", "created_at",
    ]
    list_filter = ["type", "status", "audience", "is_permanent"]
    search_fields = ["title", "body"]
    autocomplete_fields = ["questionnaire", "creator"]
    date_hierarchy = "created_at"
    actions = ["archive_selected"]

    @admin.action(description="归档")
    def archive_selected(self, request, queryset):
        """批量归档征集：收件中 / 复审中 → 已归档。其它类型跳过。"""
        if not request.user.has_perm("activities.manage_activity"):
            self.message_user(request, "没有归档权限。", level=messages.ERROR)
            return
        ok = skip = 0
        for activity in queryset:
            if archive(activity, request.user):
                ok += 1
            else:
                skip += 1
        self.message_user(request, f"已归档 {ok} 个征集。跳过 {skip} 个。")

    @admin.display(description="问卷")
    def questionnaire_link(self, obj):
        if not obj.questionnaire_id:
            return "—"
        url = reverse("admin:activities_questionnaire_change", args=[obj.questionnaire_id])
        return format_html('<a href="{}">{}</a>', url, obj.questionnaire)


class OrphanedSurveyFilter(admin.SimpleListFilter):
    """无活动引用的调研问卷（B8）。

    删活动时 `Activity.questionnaire` 是 `SET_NULL`，问卷留下来继续持有作答——
    作答是历史资产，绝不连带删除。这类问卷在列表里不可见会变成沉默的黑洞，
    所以单独一个筛选项。

    **`kind=join` 不算孤儿**：它本来就不属于任何活动，是全局单例。
    """

    title = "孤儿问卷"
    parameter_name = "orphaned"

    def lookups(self, request, model_admin):
        return (("yes", "是（无活动引用）"), ("no", "否"))

    def queryset(self, request, queryset):
        orphaned = models.Q(kind=Questionnaire.KIND_SURVEY) & models.Q(
            survey_activity__isnull=True
        )
        if self.value() == "yes":
            return queryset.filter(orphaned)
        if self.value() == "no":
            return queryset.exclude(orphaned)
        return queryset


@admin.register(Questionnaire)
class QuestionnaireAdmin(SurveyJSAdminMixin, admin.ModelAdmin):
    list_display = [
        "id", "kind", "title", "activity_link", "response_count", "updated_at",
    ]
    list_filter = ["kind", OrphanedSurveyFilter]
    search_fields = ["title", "id"]
    date_hierarchy = "updated_at"

    def get_queryset(self, request):
        # response_count 每行一次 count → 一次 annotate 解决
        return super().get_queryset(request).annotate(
            _response_count=models.Count("responses")
        )

    @admin.display(description="作答数", ordering="_response_count")
    def response_count(self, obj):
        return getattr(obj, "_response_count", 0)

    @admin.display(description="调研活动")
    def activity_link(self, obj):
        activity = getattr(obj, "survey_activity", None)
        if activity is None:
            return "—"
        url = reverse("admin:activities_activity_change", args=[activity.pk])
        return format_html('<a href="{}">{}</a>', url, activity.title)

    def survey_can_save_schema(self, obj):
        if obj.kind == Questionnaire.KIND_JOIN:
            return True
        activity = getattr(obj, "survey_activity", None)
        if activity is None:
            return not obj.responses.exists()
        return can_edit_schema(activity)

    def survey_locked_message(self, obj):
        return "已有作答或已截止，问卷 Schema 已锁定。"

    def iter_survey_responses(self, obj):
        for row in obj.responses.select_related("user").all():
            yield {
                "answers": row.answers or {},
                "user_label": (
                    row.user.username if row.user_id
                    else (f"访客 · {row.device_id[:8]}" if row.device_id else "访客")
                ),
                "submitted_at": row.submitted_at,
                "admin_url": reverse(
                    "admin:activities_questionnaireresponse_survey_view", args=[row.pk],
                ),
            }

    actions = [
        "export_stats_csv", "export_stats_pdf",
        "export_responses_csv", "export_responses_pdf",
    ]

    def _export(self, request, queryset, kind, fmt):
        """导出动作共用：单选直出；多选聚合为单个文件（一次下载全部）。"""
        questionnaires = list(queryset.order_by("pk"))
        if not questionnaires:
            return None
        data, content_type, filename = (
            survey_export.export_stats(questionnaires, fmt)
            if kind == "stats"
            else survey_export.export_responses(questionnaires, fmt)
        )
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @admin.action(description="导出统计（CSV）")
    def export_stats_csv(self, request, queryset):
        return self._export(request, queryset, "stats", "csv")

    @admin.action(description="导出统计（PDF）")
    def export_stats_pdf(self, request, queryset):
        return self._export(request, queryset, "stats", "pdf")

    @admin.action(description="导出全部作答（CSV）")
    def export_responses_csv(self, request, queryset):
        return self._export(request, queryset, "responses", "csv")

    @admin.action(description="导出全部作答（PDF）")
    def export_responses_pdf(self, request, queryset):
        return self._export(request, queryset, "responses", "pdf")

    def has_add_permission(self, request):
        # 允许后台直接新建独立问卷（默认「调研」）；「自我介绍」为单例，
        # 由数据库唯一约束兜底。
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.kind == Questionnaire.KIND_JOIN:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(QuestionnaireResponse)
class QuestionnaireResponseAdmin(SurveyJSResponseViewMixin, admin.ModelAdmin):
    list_display = [
        "questionnaire", "user", "device_id", "submitted_at",
        "response_link", "dashboard_link",
    ]
    list_filter = ["questionnaire__kind"]
    search_fields = ["questionnaire__schema", "user__username", "device_id"]
    autocomplete_fields = ["questionnaire", "user"]
    readonly_fields = ["answers", "submitted_at", "device_id"]
    date_hierarchy = "submitted_at"
    actions = ["export_selected_csv", "export_selected_pdf"]

    @admin.action(description="导出为 CSV")
    def export_selected_csv(self, request, queryset):
        return self._export_selected(queryset, "csv")

    @admin.action(description="导出为 PDF")
    def export_selected_pdf(self, request, queryset):
        return self._export_selected(queryset, "pdf")

    def _export_selected(self, queryset, fmt):
        """导出勾选的作答（多选聚合为单个文件）。"""
        rows = list(queryset.select_related("user", "questionnaire"))
        if not rows:
            return None
        data, content_type, filename = survey_export.export_selected_responses(rows, fmt)
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("questionnaire", "user")

    def _results_url(self, obj):
        if not obj or not obj.questionnaire_id:
            return None
        return reverse(
            "admin:activities_questionnaire_survey_results", args=[obj.questionnaire_id],
        )

    def get_response_stats_url(self, obj):
        return self._results_url(obj)

    @admin.display(description="查看作答")
    def response_link(self, obj):
        url = reverse("admin:activities_questionnaireresponse_survey_view", args=[obj.pk])
        return format_html('<a href="{}">查看作答</a>', url)

    @admin.display(description="统计")
    def dashboard_link(self, obj):
        url = self._results_url(obj)
        if not url:
            return "—"
        return format_html('<a href="{}">统计</a>', url)


@admin.register(VoteOption)
class VoteOptionAdmin(admin.ModelAdmin):
    list_display = ["text", "activity", "order", "created_at"]
    list_filter = ["activity__type"]
    search_fields = ["text"]
    autocomplete_fields = ["activity"]


@admin.register(Ballot)
class BallotAdmin(admin.ModelAdmin):
    list_display = ["activity", "voter", "voter_ip", "device_id", "created_at"]
    list_filter = ["activity__type"]
    search_fields = ["activity__title", "voter__username", "device_id"]
    autocomplete_fields = ["activity", "voter"]


@admin.register(BallotSelection)
class BallotSelectionAdmin(admin.ModelAdmin):
    list_display = ["ballot", "option", "created_at"]
    search_fields = ["option__text"]
    autocomplete_fields = ["ballot", "option"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["activity", "submitter", "review_status", "moderated_at", "created_at"]
    list_filter = ["review_status", "activity__type"]
    search_fields = ["activity__title", "submitter__username", "moderation_note"]
    autocomplete_fields = ["activity", "submitter", "moderated_by"]
