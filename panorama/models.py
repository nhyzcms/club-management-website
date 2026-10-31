"""校园全景图：等距柱状原图 + 多级层级图（切片产物落 media，浏览侧只吃层级图）。

设计要点（见 docs/adr/0022-campus-panorama-library.md）：

- ``source`` 原图仅作存档与重切片的输入，**永不出现在浏览路径上**——首屏只加载
  预览图与当前视野的层级图，把单个场景从 5~8MB 整图降到几百 KB；
- 层级图落 ``MEDIA_ROOT/panorama/tiles/<uuid>/<z>.jpg``（每级一整幅，Marzipano
  ``EquirectGeometry`` 一层一图的取片单位），由 nginx 直供并长缓存；
- 记录删除时连产物一起回收（``post_delete`` 信号 + ``delete_assets()``）。
"""
import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

from common.uploads import safe_extension

from .tiling import delete_prefix


def panorama_source_path(instance, filename):
    extension = safe_extension(filename, ".jpg")
    return f"panorama/sources/{uuid.uuid4().hex}{extension}"


def new_tile_dir() -> str:
    return f"panorama/tiles/{uuid.uuid4().hex}"


class Panorama(models.Model):
    """一张可球面浏览的校园全景图（等距柱状 / equirectangular）。"""

    PROJECTION_EQUIRECTANGULAR = "equirectangular"
    PROJECTION_CHOICES = [
        (PROJECTION_EQUIRECTANGULAR, "等距柱状（equirectangular）"),
    ]

    ORIGIN_UPLOAD = "upload"
    ORIGIN_DJI = "dji"
    ORIGIN_IMPORT = "import"
    ORIGIN_CHOICES = [
        (ORIGIN_UPLOAD, "手动上传"),
        (ORIGIN_DJI, "DJI 全景图导入"),
        (ORIGIN_IMPORT, "静态素材导入"),
    ]

    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PROCESSING, "切片中"),
        (STATUS_READY, "可浏览"),
        (STATUS_FAILED, "切片失败"),
    ]

    title = models.CharField("标题", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    order = models.PositiveSmallIntegerField("排序", default=0)
    is_published = models.BooleanField("公开", default=True)

    # ── 原图（存档 / 重切片输入，不经浏览路径对外）────────────────────────
    source = models.ImageField("原图", upload_to=panorama_source_path, blank=True)
    source_name = models.CharField("原文件名", max_length=255, blank=True, default="")
    source_bytes = models.BigIntegerField("原图大小（字节）", default=0)
    width = models.PositiveIntegerField("宽", default=0)
    height = models.PositiveIntegerField("高", default=0)
    projection = models.CharField(
        "投影",
        max_length=32,
        choices=PROJECTION_CHOICES,
        default=PROJECTION_EQUIRECTANGULAR,
    )

    # ── 展示适配（从 XMP 读出，可人工微调）────────────────────────────────
    initial_yaw = models.FloatField("初始偏航角（度）", default=0.0)
    initial_pitch = models.FloatField("初始俯仰角（度）", default=0.0)
    initial_fov = models.FloatField("初始视场角（度）", default=100.0)
    capture_heading = models.FloatField("拍摄朝向（度）", null=True, blank=True)

    # ── 来源元数据 ────────────────────────────────────────────────────────
    origin = models.CharField(
        "来源", max_length=16, choices=ORIGIN_CHOICES, default=ORIGIN_UPLOAD,
    )
    device_model = models.CharField("设备型号", max_length=120, blank=True, default="")
    metadata = models.JSONField("元数据", default=dict, blank=True)

    # ── 切片产物（值均为相对 MEDIA_ROOT 的路径）──────────────────────────
    tile_dir = models.CharField("瓦片目录", max_length=160, blank=True, default="")
    tile_levels = models.JSONField("瓦片层级", default=list, blank=True)
    preview_name = models.CharField("预览图", max_length=255, blank=True, default="")
    thumb_name = models.CharField("缩略图", max_length=255, blank=True, default="")

    status = models.CharField(
        "切片状态", max_length=16, choices=STATUS_CHOICES, default=STATUS_PROCESSING,
    )
    error = models.TextField("失败原因", blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="panoramas",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "校园全景图"
        verbose_name_plural = "校园全景图"
        ordering = ["order", "-created_at"]
        permissions = [
            ("manage_panoramas", "可管理校园全景图"),
        ]

    def __str__(self):
        return self.title

    # ── URL 助手（序列化器与前端取片模板共用）────────────────────────────
    def asset_url(self, name: str) -> str | None:
        return default_storage.url(name) if name else None

    @property
    def preview_url(self) -> str | None:
        """预览图（最小层整幅，~1024×512）：首屏兜底与分享图。"""
        return self.asset_url(self.preview_name)

    @property
    def thumb_url(self) -> str | None:
        """缩略图（~640×320）：列表卡片用。"""
        return self.asset_url(self.thumb_name)

    @property
    def tile_url_template(self) -> str | None:
        """Marzipano 取片模板，``{z}`` 由前端按层级索引替换。

        只含 ``{z}``：``EquirectGeometry`` 的每层是一整幅图（``EquirectTile``
        仅携带 ``z``），``{y}`` / ``{x}`` 属立方体贴图的记法——写上会被替换为
        空串（``…/1//.jpg``）导致全量 404（见 ADR-0022 修订）。
        """
        if not self.tile_dir:
            return None
        return f"{default_storage.url(self.tile_dir)}/{{z}}.jpg"

    def delete_assets(self) -> None:
        """回收瓦片目录 + 预览 / 缩略图，并就地清空对应字段值（幂等）。"""
        if self.tile_dir:
            delete_prefix(self.tile_dir)
        for name in (self.preview_name, self.thumb_name):
            if name and default_storage.exists(name):
                default_storage.delete(name)
        self.tile_dir = ""
        self.tile_levels = []
        self.preview_name = ""
        self.thumb_name = ""


@receiver(post_delete, sender=Panorama)
def _purge_panorama_assets(sender, instance: Panorama, **kwargs):
    """记录删除即回收磁盘产物（含 queryset.delete() 这条路）。"""
    instance.delete_assets()
