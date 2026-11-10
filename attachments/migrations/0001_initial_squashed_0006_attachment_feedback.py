"""Squash attachments 0001–0006.

New installs create Attachment with a feedback FK (never proposal). Existing
databases that already applied 0001–0006 treat this as already applied via
``replaces`` and do not re-run CreateModel.
"""
import collections
import uuid

import django.db.models.deletion
import django_fsm
import jsonfield.fields
import rest_framework_tus.models
from django.conf import settings
from django.db import migrations, models

import attachments.models


class Migration(migrations.Migration):

    initial = True

    replaces = [
        ("attachments", "0001_initial"),
        ("attachments", "0002_tusupload"),
        ("attachments", "0003_remove_attachment_attachment_exactly_one_parent_and_more"),
        ("attachments", "0004_remove_attachment_attachment_exactly_one_parent_and_more"),
        ("attachments", "0005_remove_attachment_attachment_exactly_one_parent_and_more"),
        ("attachments", "0006_attachment_feedback"),
    ]

    dependencies = [
        ("activities", "0008_alter_activity_type_exhibit_exhibitrating"),
        ("news", "0002_create_info_group"),
        ("reviews", "0006_feedback_report_models"),
        ("tasks", "0002_delete_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TusUpload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("guid", models.UUIDField(default=uuid.uuid4, unique=True, verbose_name="GUID")),
                ("state", django_fsm.FSMField(default="initial", max_length=50)),
                ("upload_offset", models.BigIntegerField(default=0)),
                ("upload_length", models.BigIntegerField(default=-1)),
                ("upload_metadata", jsonfield.fields.JSONField(load_kwargs={"object_pairs_hook": collections.OrderedDict})),
                ("filename", models.CharField(blank=True, max_length=255)),
                ("temporary_file_path", models.CharField(max_length=4096, null=True)),
                ("expires", models.DateTimeField(blank=True, null=True)),
                ("uploaded_file", models.FileField(blank=True, max_length=255, null=True, upload_to=rest_framework_tus.models.custom_upload_path, verbose_name="完成文件")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tus_uploads", to=settings.AUTH_USER_MODEL, verbose_name="上传者")),
            ],
            options={
                "verbose_name": "tus 上传",
                "verbose_name_plural": "tus 上传",
            },
        ),
        migrations.CreateModel(
            name="Attachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=attachments.models.attachment_upload_path, verbose_name="文件")),
                ("file_type", models.CharField(choices=[("image", "图片"), ("video", "视频"), ("document", "文档"), ("archive", "压缩包"), ("other", "其他")], max_length=20, verbose_name="文件类型")),
                ("file_name", models.CharField(max_length=255, verbose_name="文件名")),
                ("file_size", models.BigIntegerField("文件大小")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("task", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="tasks.task", verbose_name="任务")),
                ("feedback", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="reviews.feedback", verbose_name="意见反馈")),
                ("news", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="news.news", verbose_name="新闻")),
                ("submission", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="activities.submission", verbose_name="作品")),
                ("exhibit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="activities.exhibit", verbose_name="展品")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="uploaded_attachments", to=settings.AUTH_USER_MODEL, verbose_name="上传者")),
            ],
            options={
                "verbose_name": "附件",
                "verbose_name_plural": "附件",
                "ordering": ["-uploaded_at"],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(exhibit__isnull=True, feedback__isnull=True, news__isnull=True, submission__isnull=True, task__isnull=False)
                            | models.Q(exhibit__isnull=True, feedback__isnull=False, news__isnull=True, submission__isnull=True, task__isnull=True)
                            | models.Q(exhibit__isnull=True, feedback__isnull=True, news__isnull=False, submission__isnull=True, task__isnull=True)
                            | models.Q(exhibit__isnull=True, feedback__isnull=True, news__isnull=True, submission__isnull=False, task__isnull=True)
                            | models.Q(exhibit__isnull=False, feedback__isnull=True, news__isnull=True, submission__isnull=True, task__isnull=True)
                        ),
                        name="attachment_exactly_one_parent",
                        violation_error_message="附件必须且只能挂在一个父级（任务/意见反馈/新闻/作品/展品）上。",
                    ),
                ],
            },
        ),
    ]
