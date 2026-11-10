"""校园全景图的导入流水线与切片编排（见 docs/adr/0022-campus-panorama-library.md）。

两种导入输入：

1. **单张全景图**——DJI Fly / DJI GO 4 合成的等距柱状 JPEG，或任意 2:1 全景图；
2. **zip 压缩包**——只作传输外壳：抽出包内最合适的那张图落进 media，**压缩包本身
   从不持久化**（解压完即丢弃），并防 zip-slip / zip bomb。

切片是**同步**的（不引入队列与后台任务框架）：本项目部署规模下 8192×4096 全量分层
约数秒，换来「失败如实回报、无悬挂状态」。切片失败不丢记录——置 ``status=failed``
+ ``error``，可经 ``POST /panorama/panoramas/{id}/reprocess/`` 或管理命令重来。
"""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import uuid
import zipfile

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError

from common.policy import format_byte_cap, get_policy

from .dji import (
    PanoramaMetadata,
    adapt_initial_view,
    device_label,
    is_equirect_ratio,
    read_metadata,
)
from .models import Panorama, new_tile_dir
from .tiling import (
    MAX_SOURCE_PIXELS,
    build_level_images,
    build_preview_and_thumb,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ARCHIVE_EXTENSIONS = {".zip"}
# 解压产物上限 = 同步上传上限 × 该倍数（防 zip bomb；上限本身由站点策略配置）。
ARCHIVE_EXPANSION_FACTOR = 4


class PanoramaImportError(Exception):
    """导入被拒（校验失败）。``reason`` 供前端分支，``message`` 面向使用者。"""

    def __init__(self, message: str, reason: str = "invalid") -> None:
        super().__init__(message)
        self.reason = reason


def is_full_equirect(meta: PanoramaMetadata) -> bool:
    """完整球面全景 = 宽高比 2:1，且 GPano 没报「这是一张裁切过的全景」。"""
    if not is_equirect_ratio(meta.width, meta.height):
        return False
    if meta.full_width and meta.cropped_width and meta.cropped_width < meta.full_width:
        return False
    return True


@contextlib.contextmanager
def resolved_source(upload):
    """把上传物归一成「一个可读的全景图文件」：图片原样，zip 解包挑图。

    产出 ``(原文件名, 文件句柄)``；临时目录随 ``with`` 退出清理——**压缩包不进 media**。
    """
    upload.seek(0)
    head = upload.read(4)
    upload.seek(0)
    if head[:2] != b"PK":
        yield (getattr(upload, "name", "") or "panorama.jpg"), upload
        return

    tmpdir = tempfile.mkdtemp(prefix="panorama-import-")
    try:
        name, path = _extract_panorama_from_archive(upload, tmpdir)
        with open(path, "rb") as handle:
            yield name, handle
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_panorama_from_archive(upload, tmpdir: str) -> tuple[str, str]:
    """从 zip 里挑出最合适的一张全景图并落盘到 ``tmpdir``。

    只读成员流、自己写到指定目标路径（**不用 ``extractall``**）→ 结构上不存在
    zip-slip（路径穿越）的利用面；成员尺寸与解压总量双重封顶。
    """
    expansion_cap = get_policy().sync_upload_max_bytes * ARCHIVE_EXPANSION_FACTOR
    try:
        archive = zipfile.ZipFile(upload)
    except zipfile.BadZipFile:
        raise PanoramaImportError("压缩包已损坏，无法解压。", reason="bad_zip")

    with archive:
        candidates = []
        expanded = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            if not base or base.startswith(".") or "__MACOSX" in info.filename:
                continue
            if os.path.splitext(base)[1].lower() not in IMAGE_EXTENSIONS:
                continue
            expanded += info.file_size
            if expanded > expansion_cap:
                raise PanoramaImportError(
                    f"压缩包解压后体积过大（上限 {format_byte_cap(expansion_cap)}）。",
                    reason="archive_too_large",
                )
            candidates.append(info)

        if not candidates:
            raise PanoramaImportError("压缩包里没有找到图片文件。", reason="no_image_in_archive")

        best, best_key = None, None
        for info in candidates:
            try:
                with archive.open(info) as handle, Image.open(handle) as img:
                    width, height = img.size
            except Exception:
                continue
            key = (1 if is_equirect_ratio(width, height) else 0, width * height)
            if best_key is None or key > best_key:
                best, best_key = info, key
        if best is None:
            raise PanoramaImportError("压缩包里的图片无法识别。", reason="unreadable_image")

        extension = os.path.splitext(best.filename)[1].lower() or ".jpg"
        destination = os.path.join(tmpdir, f"source{extension}")
        with archive.open(best) as source, open(destination, "wb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)

    return os.path.basename(best.filename), destination


def _read_and_validate(handle, name: str) -> tuple[PanoramaMetadata, int]:
    """读出元数据并做全部准入校验；不通过抛 ``PanoramaImportError``。"""
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(0)
    if size <= 0:
        raise PanoramaImportError("上传的文件是空的。", reason="empty_file")

    # 同步上传上限复用站点策略（后台「站点策略 → 上传」可调），不另造旋钮。
    cap = get_policy().sync_upload_max_bytes
    if size > cap:
        raise PanoramaImportError(
            f"文件不能超过 {format_byte_cap(cap)}。", reason="too_large",
        )

    extension = os.path.splitext(name)[1].lower()
    if extension and extension not in IMAGE_EXTENSIONS | ARCHIVE_EXTENSIONS:
        raise PanoramaImportError(
            "只支持 JPEG / PNG / WebP 图片，或装着全景图的 zip。",
            reason="unsupported_format",
        )

    try:
        meta = read_metadata(handle)
    except UnidentifiedImageError:
        raise PanoramaImportError(
            "无法识别的图片格式（仅支持 JPEG / PNG / WebP）。", reason="unsupported_image",
        )

    if meta.width * meta.height > MAX_SOURCE_PIXELS:
        raise PanoramaImportError("图片像素过大，无法处理。", reason="too_many_pixels")

    if not is_full_equirect(meta):
        raise PanoramaImportError(
            "这不是一张可用的球面全景图：需要宽高比 2:1 的等距柱状（equirectangular）图。"
            "DJI 设备请用「全景 → 球面 / Sphere」模式，或用 DJI Fly 导出的 360 全景原图"
            "（广角 / 竖幅 / 自拍模式拍出的不是完整球面，无法球面浏览）。",
            reason="not_equirectangular",
        )
    return meta, size


def _metadata_payload(meta: PanoramaMetadata) -> dict:
    """入库的元数据快照：GPano / drone-dji 全量 + 机型（便于事后追溯与适配）。"""
    return {
        "make": meta.make,
        "model": meta.model,
        "projection": meta.projection,
        "full_pano_width": meta.full_width or None,
        "cropped_area_width": meta.cropped_width or None,
        "gpano": {k: v for k, v in meta.fields.items() if k.startswith("GPano:")},
        "dji": {k: v for k, v in meta.fields.items() if k.startswith("drone-dji:")},
    }


def import_panorama(
    *,
    upload,
    title: str,
    description: str = "",
    order: int = 0,
    is_published: bool = True,
    user=None,
    origin: str | None = None,
) -> Panorama:
    """导入一张全景图：校验 → 落原图 → 切片 → 就绪。

    校验失败（非全景图 / 超限 / 坏包）抛 ``PanoramaImportError``，**不留记录**；
    切片失败保留记录并置 ``status=failed``（可重切片），由调用方按需回报。
    """
    with resolved_source(upload) as (name, handle):
        meta, size = _read_and_validate(handle, name)
        yaw, pitch, fov = adapt_initial_view(meta)
        panorama = Panorama.objects.create(
            title=title[:200],
            description=description[:2000],
            order=order,
            is_published=is_published,
            origin=origin or (Panorama.ORIGIN_DJI if meta.is_dji else Panorama.ORIGIN_UPLOAD),
            source_name=os.path.basename(name)[:255],
            source_bytes=size,
            width=meta.width,
            height=meta.height,
            projection=Panorama.PROJECTION_EQUIRECTANGULAR,
            initial_yaw=yaw,
            initial_pitch=pitch,
            initial_fov=fov,
            capture_heading=meta.heading_degrees,
            device_model=device_label(meta)[:120],
            metadata=_metadata_payload(meta),
            created_by=user,
            status=Panorama.STATUS_PROCESSING,
        )
        handle.seek(0)
        panorama.source.save(os.path.basename(name) or "panorama.jpg", File(handle), save=False)
        panorama.save(update_fields=["source"])

    try:
        process_panorama(panorama)
    except Exception as exc:  # noqa: BLE001 —— 失败如实落库，记录不丢
        panorama.status = Panorama.STATUS_FAILED
        panorama.error = f"{exc.__class__.__name__}: {exc}"[:2000]
        panorama.save(update_fields=["status", "error", "updated_at"])
    return panorama


def process_panorama(panorama: Panorama) -> Panorama:
    """（重新）切片：读存档原图 → 多级层级图 + 预览 + 缩略图 → ``status=ready``。"""
    if not panorama.source:
        raise ValueError("该条目没有可用的原图")

    panorama.delete_assets()
    with default_storage.open(panorama.source.name, "rb") as handle:
        with Image.open(handle) as img:
            rgb = img.convert("RGB")
            tile_dir = new_tile_dir()
            levels = build_level_images(rgb, tile_dir)
            preview_bytes, thumb_bytes = build_preview_and_thumb(rgb)

    panorama.tile_dir = tile_dir
    panorama.tile_levels = levels
    panorama.preview_name = default_storage.save(
        f"panorama/assets/preview-{uuid.uuid4().hex}.jpg", ContentFile(preview_bytes),
    )
    panorama.thumb_name = default_storage.save(
        f"panorama/assets/thumb-{uuid.uuid4().hex}.jpg", ContentFile(thumb_bytes),
    )
    panorama.status = Panorama.STATUS_READY
    panorama.error = ""
    panorama.save(update_fields=[
        "tile_dir", "tile_levels", "preview_name", "thumb_name",
        "status", "error", "updated_at",
    ])
    return panorama
