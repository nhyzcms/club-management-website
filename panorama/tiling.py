"""等距柱状全景图的层级图生成（纯 Pillow，无外部二进制依赖）。

产物布局（相对 MEDIA_ROOT，**必须与 Marzipano ``EquirectGeometry`` 的取片模型一致**）：

    panorama/tiles/<uuid>/<z>.jpg   层级图，z=0 是最小层，每级一整幅等距柱状图
    panorama/assets/*.jpg           预览图（最小层整幅）与缩略图（列表用）

为什么分层：原静态全景页把 8MB 原图整张交给 WebGL，手机 GPU 纹理上限（4096 / 8192）
直接超限 → 白屏或极慢。分层后首屏只需最小层（~90KB），细节层随视野按需补齐。

为什么每级是**一整幅**而不是 512px 网格：Marzipano 的 ``EquirectGeometry`` 以
「一层一张等距柱状图」为取片单位（其 ``EquirectTile`` 只携带 ``z``），URL 模板
只认 ``{z}`` 占位符；``{z}/{y}/{x}`` 网格是立方体贴图的记法，套在 equirect 上
会让 ``{y}``/``{x}`` 替换为空串、全量 404（2026-10-12 修复——见 ADR-0022 修订）。
"""
from __future__ import annotations

import io

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image

# 层级宽度（2 的幂）。源图更宽时在切片阶段降采样到 MAX_LEVEL_WIDTH——原图仍完整存档。
LEVEL_WIDTHS = (1024, 2048, 4096, 8192)
PREVIEW_WIDTH = 1024
THUMB_WIDTH = 640
JPEG_QUALITY = 82

# 像素上限：8192×4096 的两倍余量，放行 DJI 常见规格、挡住「解压炸弹」式巨图。
MAX_SOURCE_PIXELS = 200_000_000
Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS


def plan_levels(width: int) -> list[int]:
    """按源图宽度挑层级：不超过源宽的 2 的幂；比最小层还窄时就用源宽本身。"""
    levels = [level for level in LEVEL_WIDTHS if level <= width]
    return levels or [max(1, width)]


def _encode_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return buffer.getvalue()


def _resized(source: Image.Image, width: int) -> Image.Image:
    height = max(1, round(width * source.height / source.width))
    if source.width == width and source.height == height:
        return source
    return source.resize((width, height), Image.LANCZOS)


def build_level_images(rgb: Image.Image, level_dir: str) -> list[dict]:
    """生成全部层级的整幅层级图，返回层级描述（写进 ``Panorama.tile_levels``）。

    逐级**减半**（从最大层往最小层走），每级只留一份位图在手，峰值内存可控；
    每级编码为 ``<level_dir>/<z>.jpg``——与 ``EquirectGeometry`` 一层一图的
    取片单位对齐（取片模板只含 ``{z}``）。
    返回形如 ``[{"z": 0, "width": 1024, "height": 512}, ...]``，``z`` 从 0（最小 / 最模糊）递增。
    """
    levels = plan_levels(rgb.width)
    records: list[dict] = []
    level_image: Image.Image | None = None

    for z in range(len(levels) - 1, -1, -1):
        target_width = levels[z]
        if level_image is None:
            level_image = _resized(rgb, target_width)
        else:
            level_image = _resized(level_image, target_width)

        default_storage.save(
            f"{level_dir}/{z}.jpg", ContentFile(_encode_jpeg(level_image))
        )
        records.append({
            "z": z,
            "width": level_image.width,
            "height": level_image.height,
        })

    records.reverse()
    return records


def build_preview_and_thumb(rgb: Image.Image) -> tuple[bytes, bytes]:
    """预览图（首屏兜底 / 分享图）与缩略图（列表卡片）各一张。"""
    return (
        _encode_jpeg(_resized(rgb, min(PREVIEW_WIDTH, rgb.width))),
        _encode_jpeg(_resized(rgb, min(THUMB_WIDTH, rgb.width))),
    )


def delete_prefix(prefix: str) -> None:
    """递归删除 storage 下整个目录（FileSystemStorage 没有目录删除语义）。

    幂等：目录 / 文件不存在一律静默跳过。
    """
    try:
        dirs, files = default_storage.listdir(prefix)
    except OSError:
        return
    for name in files:
        try:
            default_storage.delete(f"{prefix}/{name}")
        except OSError:
            pass
    for name in dirs:
        delete_prefix(f"{prefix}/{name}")
