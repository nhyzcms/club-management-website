from django.contrib import admin

from .models import Exam, ExamBatch, ExamErrata, ExamSubject


class ExamSubjectInline(admin.TabularInline):
    model = ExamSubject
    extra = 0


class ExamBatchInline(admin.TabularInline):
    model = ExamBatch
    extra = 0
    show_change_link = True


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "updated_at")
    inlines = [ExamBatchInline]


@admin.register(ExamBatch)
class ExamBatchAdmin(admin.ModelAdmin):
    list_display = ("name", "exam", "sort_order")
    inlines = [ExamSubjectInline]


@admin.register(ExamErrata)
class ExamErrataAdmin(admin.ModelAdmin):
    list_display = ("id", "text", "created_at", "dismissed_at")
    readonly_fields = ("created_at",)
