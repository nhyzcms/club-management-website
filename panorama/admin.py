from django.contrib import admin

from .models import Panorama


@admin.register(Panorama)
class PanoramaAdmin(admin.ModelAdmin):
    """后台只做查看与微调：新增 / 上传走门户（切片流水线在服务层）。

    ``has_add_permission`` 恒 False——在后台直接建行不会跑切片，只会产出
    无瓦片的坏记录；上传入口在门户的全景图管理页（或 ``import_static_panoramas``）。
    """

    list_display = (
        "order", "title", "status", "origin", "device_model",
        "width", "height", "is_published", "updated_at",
    )
    list_filter = ("status", "origin", "is_published")
    search_fields = ("title", "description", "source_name", "device_model")
    ordering = ("order", "-created_at")
    readonly_fields = (
        "source", "source_name", "source_bytes", "width", "height",
        "projection", "origin", "device_model", "metadata", "capture_heading",
        "tile_dir", "tile_levels", "preview_name", "thumb_name",
        "status", "error", "created_by", "created_at", "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("title", "description", "order", "is_published")}),
        ("展示适配", {"fields": ("initial_yaw", "initial_pitch", "initial_fov")}),
        ("原图与元数据", {
            "fields": (
                "source", "source_name", "source_bytes", "width", "height",
                "projection", "origin", "device_model", "capture_heading", "metadata",
            ),
        }),
        ("切片产物", {
            "fields": (
                "status", "error", "tile_dir", "tile_levels",
                "preview_name", "thumb_name",
            ),
        }),
        ("审计", {"fields": ("created_by", "created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return False
