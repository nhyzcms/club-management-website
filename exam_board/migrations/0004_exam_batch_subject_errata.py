from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import exam_board.models


def copy_legacy_exams(apps, schema_editor):
    ExamData = apps.get_model("exam_board", "ExamData")
    Exam = apps.get_model("exam_board", "Exam")
    ExamBatch = apps.get_model("exam_board", "ExamBatch")
    for old in ExamData.objects.all().order_by("id"):
        exam = Exam.objects.create(
            title=(old.exam_title or "考试")[:50],
            updated_by_id=getattr(old, "updated_by_id", None),
        )
        ExamBatch.objects.create(exam=exam, name="默认", sort_order=0)


def grant_exam_perms(apps, schema_editor):
    from django.apps import apps as real_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)

    group, _ = Group.objects.get_or_create(name="信息组")
    for codename in ("add_exam", "change_exam", "delete_exam"):
        perm = Permission.objects.get(content_type__app_label="exam_board", codename=codename)
        group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("exam_board", "0003_grant_exam_to_info_group"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Exam",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=50, verbose_name="考试标题")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="exam_records",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="写入人",
                    ),
                ),
            ],
            options={
                "verbose_name": "考试",
                "verbose_name_plural": "考试",
                "ordering": ["-id"],
            },
        ),
        migrations.CreateModel(
            name="ExamBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, verbose_name="批次名称")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="排序")),
                (
                    "exam",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="batches",
                        to="exam_board.exam",
                        verbose_name="考试",
                    ),
                ),
            ],
            options={
                "verbose_name": "考试批次",
                "verbose_name_plural": "考试批次",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="ExamSubject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=30, verbose_name="科目")),
                ("exam_date", models.DateField(verbose_name="考试日期")),
                ("start_time", models.TimeField(verbose_name="开始时间")),
                ("end_time", models.TimeField(verbose_name="结束时间")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="排序")),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subjects",
                        to="exam_board.exambatch",
                        verbose_name="批次",
                    ),
                ),
            ],
            options={
                "verbose_name": "科目场次",
                "verbose_name_plural": "科目场次",
                "ordering": ["exam_date", "start_time", "sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="ExamErrata",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.CharField(blank=True, max_length=500, verbose_name="说明")),
                ("image", models.ImageField(blank=True, upload_to=exam_board.models.errata_upload_path, verbose_name="图片")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dismissed_at", models.DateTimeField(blank=True, null=True, verbose_name="撤回时间")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="exam_errata",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="发布人",
                    ),
                ),
            ],
            options={
                "verbose_name": "题目误刊",
                "verbose_name_plural": "题目误刊",
                "ordering": ["-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="exambatch",
            constraint=models.UniqueConstraint(fields=("exam", "name"), name="exam_batch_unique_name"),
        ),
        migrations.RunPython(copy_legacy_exams, migrations.RunPython.noop),
        migrations.DeleteModel(name="ExamData"),
        migrations.RunPython(grant_exam_perms, migrations.RunPython.noop),
    ]
