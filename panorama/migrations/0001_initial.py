import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import panorama.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Panorama",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("title", models.CharField(max_length=200, verbose_name="标题")),
                ("description", models.TextField(blank=True, default="", verbose_name="描述")),
                ("order", models.PositiveSmallIntegerField(default=0, verbose_name="排序")),
                ("is_published", models.BooleanField(default=True, verbose_name="公开")),
                (
                    "source",
                    models.ImageField(
                        blank=True,
                        upload_to=panorama.models.panorama_source_path,
                        verbose_name="原图",
                    ),
                ),
                (
                    "source_name",
                    models.CharField(blank=True, default="", max_length=255, verbose_name="原文件名"),
                ),
                ("source_bytes", models.BigIntegerField(default=0, verbose_name="原图大小（字节）")),
                ("width", models.PositiveIntegerField(default=0, verbose_name="宽")),
                ("height", models.PositiveIntegerField(default=0, verbose_name="高")),
                (
                    "projection",
                    models.CharField(
                        choices=[("equirectangular", "等距柱状（equirectangular）")],
                        default="equirectangular",
                        max_length=32,
                        verbose_name="投影",
                    ),
                ),
                ("initial_yaw", models.FloatField(default=0.0, verbose_name="初始偏航角（度）")),
                ("initial_pitch", models.FloatField(default=0.0, verbose_name="初始俯仰角（度）")),
                ("initial_fov", models.FloatField(default=100.0, verbose_name="初始视场角（度）")),
                (
                    "capture_heading",
                    models.FloatField(blank=True, null=True, verbose_name="拍摄朝向（度）"),
                ),
                (
                    "origin",
                    models.CharField(
                        choices=[
                            ("upload", "手动上传"),
                            ("dji", "DJI 全景图导入"),
                            ("import", "静态素材导入"),
                        ],
                        default="upload",
                        max_length=16,
                        verbose_name="来源",
                    ),
                ),
                (
                    "device_model",
                    models.CharField(blank=True, default="", max_length=120, verbose_name="设备型号"),
                ),
                ("metadata", models.JSONField(blank=True, default=dict, verbose_name="元数据")),
                (
                    "tile_dir",
                    models.CharField(blank=True, default="", max_length=160, verbose_name="瓦片目录"),
                ),
                ("tile_levels", models.JSONField(blank=True, default=list, verbose_name="瓦片层级")),
                ("tile_size", models.PositiveSmallIntegerField(default=512, verbose_name="瓦片边长")),
                (
                    "preview_name",
                    models.CharField(blank=True, default="", max_length=255, verbose_name="预览图"),
                ),
                (
                    "thumb_name",
                    models.CharField(blank=True, default="", max_length=255, verbose_name="缩略图"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("processing", "切片中"), ("ready", "可浏览"), ("failed", "切片失败")],
                        default="processing",
                        max_length=16,
                        verbose_name="切片状态",
                    ),
                ),
                ("error", models.TextField(blank=True, default="", verbose_name="失败原因")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="panoramas",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="创建者",
                    ),
                ),
            ],
            options={
                "verbose_name": "校园全景图",
                "verbose_name_plural": "校园全景图",
                "ordering": ["order", "-created_at"],
                "permissions": [("manage_panoramas", "可管理校园全景图")],
            },
        ),
    ]
