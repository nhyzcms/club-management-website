"""Shared Django-admin SurveyJS editor, VisualizationPanel, and single-response views.

Vanilla SurveyJS (not the SPA) under admin auth + model perms. Schema JSON is
the same field the portal edits; results stay admin-only (ADR 0011 / 0014).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from django.contrib.admin import AdminSite, ModelAdmin
from django.core.exceptions import PermissionDenied
from django.db.models.options import Options
from django.http import Http404, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse


class SurveyJSAdminMixin:
    """Adds ``<object_id>/survey-editor/`` and ``<object_id>/survey-results/``.

    Subclasses expose a ``schema`` JSONField. Override the hooks below when the
    source object is not itself the questionnaire (or when save should be gated).
    """

    change_form_template = "admin/surveyjs/change_form.html"
    admin_site: AdminSite
    opts: Options

    if TYPE_CHECKING:
        def has_change_permission(self, request, obj=None) -> bool: ...

    def get_survey_schema(self, obj):
        return obj.schema or {}

    def save_survey_schema(self, obj, schema):
        obj.schema = schema
        obj.save()

    def survey_is_applicable(self, obj):
        return True

    def survey_can_save_schema(self, obj):
        return True

    def survey_locked_message(self, obj):
        return "问卷已锁定，无法保存。"

    def iter_survey_responses(self, obj):
        """Yield dicts: answers, user_label, submitted_at, admin_url (optional)."""
        return []

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        extra = [
            path(
                "<path:object_id>/survey-editor/",
                self.admin_site.admin_view(self.survey_editor_view),
                name="%s_%s_survey_editor" % info,
            ),
            path(
                "<path:object_id>/survey-results/",
                self.admin_site.admin_view(self.survey_results_view),
                name="%s_%s_survey_results" % info,
            ),
        ]
        return extra + cast(ModelAdmin, super()).get_urls()

    def _survey_obj(self, request, object_id):
        obj = cast(ModelAdmin, self).get_object(request, object_id)
        if obj is None:
            raise Http404
        if not self.has_view_or_change_permission(request, obj): # pyright: ignore[reportAttributeAccessIssue]
            raise PermissionDenied
        if not self.survey_is_applicable(obj):
            raise Http404
        return obj

    def survey_editor_view(self, request, object_id):
        obj = self._survey_obj(request, object_id)
        can_change = self.has_change_permission(request, obj)
        schema_editable = self.survey_can_save_schema(obj)
        can_save = can_change and schema_editable
        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                return JsonResponse({"ok": False, "error": "没有修改权限。"}, status=403)
            if not self.survey_can_save_schema(obj):
                return JsonResponse(
                    {"ok": False, "error": self.survey_locked_message(obj)},
                    status=400,
                )
            try:
                payload = json.loads(request.body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return JsonResponse({"ok": False, "error": "无效 JSON。"}, status=400)
            schema = payload.get("schema", payload)
            if not isinstance(schema, dict):
                return JsonResponse({"ok": False, "error": "schema 必须是对象。"}, status=400)
            self.save_survey_schema(obj, schema)
            return JsonResponse({"ok": True})

        info = self.opts.app_label, self.opts.model_name
        context = {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "original": obj,
            "title": "编辑问卷",
            "schema_json": self.get_survey_schema(obj),
            "can_save": can_save,
            "locked_message": (
                "" if can_save
                else ("没有修改权限。" if not can_change else self.survey_locked_message(obj))
            ),
            "save_url": request.path,
            "back_url": reverse("admin:%s_%s_change" % info, args=[obj.pk]),
        }
        return TemplateResponse(request, "admin/surveyjs/editor.html", context)

    def survey_results_view(self, request, object_id):
        obj = self._survey_obj(request, object_id)
        rows = list(self.iter_survey_responses(obj))
        info = self.opts.app_label, self.opts.model_name
        context = {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "original": obj,
            "title": "统计",
            "schema_json": self.get_survey_schema(obj),
            "answers_json": [r.get("answers") or {} for r in rows],
            "response_rows": rows,
            "back_url": reverse("admin:%s_%s_change" % info, args=[obj.pk]),
        }
        return TemplateResponse(request, "admin/surveyjs/results.html", context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = cast(ModelAdmin, self).get_object(request, object_id)
        if obj is not None and self.survey_is_applicable(obj):
            info = self.opts.app_label, self.opts.model_name
            extra_context["survey_editor_url"] = reverse(
                "admin:%s_%s_survey_editor" % info, args=[obj.pk],
            )
            extra_context["survey_results_url"] = reverse(
                "admin:%s_%s_survey_results" % info, args=[obj.pk],
            )
        return cast(ModelAdmin, super()).change_view(
            request, object_id, form_url, extra_context=extra_context,
        )


class SurveyJSResponseViewMixin:
    """Adds ``<object_id>/survey-view/`` — one filled questionnaire in display mode.

    Expects a response object with ``answers`` and a related questionnaire that
    exposes ``schema``. Override the hooks below when the shape differs.
    """

    change_form_template = "admin/surveyjs/change_form.html"
    admin_site: AdminSite
    opts: Options

    def get_response_schema(self, obj):
        questionnaire = getattr(obj, "questionnaire", None)
        if questionnaire is None:
            return {}
        return questionnaire.schema or {}

    def get_response_answers(self, obj):
        return obj.answers or {}

    def get_response_user_label(self, obj):
        user = getattr(obj, "user", None)
        if user is not None:
            return user.get_username()
        device_id = getattr(obj, "device_id", "") or ""
        if device_id:
            return f"访客 · {device_id[:8]}"
        return "访客"

    def get_response_submitted_at(self, obj):
        return getattr(obj, "submitted_at", None)

    def get_response_stats_url(self, obj):
        return None

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        extra = [
            path(
                "<path:object_id>/survey-view/",
                self.admin_site.admin_view(self.survey_response_view),
                name="%s_%s_survey_view" % info,
            ),
        ]
        return extra + cast(ModelAdmin, super()).get_urls()

    def survey_response_view(self, request, object_id):
        obj = cast(ModelAdmin, self).get_object(request, object_id)
        if obj is None:
            raise Http404
        if not self.has_view_or_change_permission(request, obj):  # pyright: ignore[reportAttributeAccessIssue]
            raise PermissionDenied
        info = self.opts.app_label, self.opts.model_name
        context = {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "original": obj,
            "title": "查看作答",
            "schema_json": self.get_response_schema(obj),
            "answers_json": self.get_response_answers(obj),
            "user_label": self.get_response_user_label(obj),
            "submitted_at": self.get_response_submitted_at(obj),
            "back_url": reverse("admin:%s_%s_change" % info, args=[obj.pk]),
            "survey_results_url": self.get_response_stats_url(obj),
        }
        return TemplateResponse(request, "admin/surveyjs/response.html", context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = cast(ModelAdmin, self).get_object(request, object_id)
        if obj is not None:
            info = self.opts.app_label, self.opts.model_name
            extra_context["survey_response_url"] = reverse(
                "admin:%s_%s_survey_view" % info, args=[obj.pk],
            )
            stats_url = self.get_response_stats_url(obj)
            if stats_url:
                extra_context["survey_results_url"] = stats_url
        return cast(ModelAdmin, super()).change_view(
            request, object_id, form_url, extra_context=extra_context,
        )
