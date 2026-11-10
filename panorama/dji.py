"""全景图元数据解析：JPEG XMP（Google Photo Sphere / DJI）→ 展示参数。

DJI 系列（DJI Fly / DJI GO 4）导出的「球面 / Sphere」全景就是 2:1 等距柱状 JPEG，
APP1 段里带两类 XMP 字段：

- ``GPano:*``    —— Google 全景图规范：投影方式、全图 / 裁切尺寸、初始视角、拍摄朝向；
- ``drone-dji:*`` —— DJI 私有字段：云台偏航角、绝对高度、经纬度、机型、拍摄时间。

本模块**只读**：识别 → 适配（把拍摄朝向折算成 viewer 初始 yaw / pitch / fov），
绝不改写上传的原图。字段缺失时全部优雅降级（不猜、不报错）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import IO

from PIL import Image

# XMP 包藏在一个 APP1 段里，段头是标准命名空间 URL + NUL。
XMP_APP1_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
_XMP_PACKET_END = b"<?xpacket end"
# 只扫文件头部：XMP 段最大 64KB，且总在 EXIF（含缩略图）之后不远处。
_XMP_SCAN_BYTES = 512 * 1024

# 完整球面全景的宽高比是 2:1；容忍 ±5%（个别设备裁掉一两行像素）。
EQUIRECT_TOLERANCE = 0.1

DEFAULT_FOV_DEGREES = 100.0
MIN_FOV_DEGREES = 30.0
MAX_FOV_DEGREES = 120.0
MAX_PITCH_DEGREES = 85.0


@dataclass
class PanoramaMetadata:
    """一张全景图的「可读事实」——像素尺寸 + XMP 读出的投影与视角。"""

    width: int = 0
    height: int = 0
    projection: str = ""
    full_width: int = 0
    cropped_width: int = 0
    heading_degrees: float | None = None
    initial_heading: float | None = None
    initial_pitch: float | None = None
    initial_fov: float | None = None
    make: str = ""
    model: str = ""
    is_dji: bool = False
    fields: dict[str, str] = field(default_factory=dict)


def extract_xmp(head: bytes) -> str:
    """从字节头部抠出 XMP 包（没有则返回空串）。"""
    start = head.find(XMP_APP1_HEADER)
    if start < 0:
        return ""
    start += len(XMP_APP1_HEADER)
    end = head.find(_XMP_PACKET_END, start)
    if end < 0:
        end = len(head)
    return head[start:end].decode("utf-8", errors="replace")


def _value(xmp: str, name: str) -> str | None:
    """取 XMP 字段值：先试属性写法 ``ns:name="v"``，再试元素写法 ``<ns:name>v</ns:name>``。"""
    match = re.search(rf'{re.escape(name)}\s*=\s*"([^"]*)"', xmp)
    if match:
        return match.group(1).strip()
    match = re.search(rf"<{re.escape(name)}>(.*?)</{re.escape(name)}>", xmp, re.S)
    if match:
        return match.group(1).strip()
    return None


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_xmp(xmp: str) -> dict[str, str]:
    """抽出 GPano / drone-dji 两个命名空间下的全部字段（两种写法都收）。"""
    found: dict[str, str] = {}
    for prefix in ("GPano", "drone-dji"):
        for match in re.finditer(rf'{prefix}:([A-Za-z0-9_]+)\s*=\s*"([^"]*)"', xmp):
            found[f"{prefix}:{match.group(1)}"] = match.group(2).strip()
        for match in re.finditer(
            rf"<{prefix}:([A-Za-z0-9_]+)>(.*?)</{prefix}:[A-Za-z0-9_]+>", xmp, re.S,
        ):
            found.setdefault(f"{prefix}:{match.group(1)}", match.group(2).strip())
    return found


def is_equirect_ratio(width: int, height: int) -> bool:
    """宽高比是否接近 2:1（等距柱状全图的基本形状特征）。"""
    if not width or not height:
        return False
    return abs(width / height - 2.0) <= EQUIRECT_TOLERANCE


def device_label(meta: PanoramaMetadata) -> str:
    """机型展示名：EXIF Model / Make 优先，回落 XMP 的 ``drone-dji:Model``。"""
    for value in (meta.model, meta.make, meta.fields.get("drone-dji:Model", "")):
        if value:
            return value
    return ""


def _exif_strings(img: Image.Image) -> tuple[str, str]:
    """EXIF 的 Make / Model（读不到就空串，绝不上抛）。"""
    try:
        exif = img.getexif()
        make = str(exif.get(271, "") or "").strip()
        model = str(exif.get(272, "") or "").strip()
    except Exception:
        return "", ""
    return make, model


def read_metadata(fp: IO[bytes]) -> PanoramaMetadata:
    """读一张全景图：像素尺寸 + EXIF 机型 + XMP（GPano / drone-dji）。

    只读文件头部（≤512KB）取 XMP，不把整张大图读进内存。
    ``fp`` 需可 seek；无法识别时由 ``Image.open`` 抛 ``UnidentifiedImageError``。
    """
    fp.seek(0)
    head = fp.read(_XMP_SCAN_BYTES)
    fp.seek(0)
    with Image.open(fp) as img:
        width, height = img.size
        make, model = _exif_strings(img)

    values = parse_xmp(extract_xmp(head))
    is_dji = (
        make.upper() == "DJI"
        or "dji" in model.lower()
        or any(key.startswith("drone-dji:") for key in values)
    )

    heading = _float(values.get("GPano:PoseHeadingDegrees"))
    if heading is None:
        heading = _float(values.get("drone-dji:GimbalYawDegree"))

    return PanoramaMetadata(
        width=width,
        height=height,
        projection=values.get("GPano:ProjectionType", ""),
        full_width=int(_float(values.get("GPano:FullPanoWidthPixels")) or 0),
        cropped_width=int(_float(values.get("GPano:CroppedAreaImageWidthPixels")) or 0),
        heading_degrees=heading,
        initial_heading=_float(values.get("GPano:InitialViewHeadingDegrees")),
        initial_pitch=_float(values.get("GPano:InitialViewPitchDegrees")),
        initial_fov=_float(values.get("GPano:InitialViewVerticalFovDegrees")),
        make=make,
        model=model,
        is_dji=is_dji,
        fields=values,
    )


def _normalize_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def adapt_initial_view(meta: PanoramaMetadata) -> tuple[float, float, float]:
    """XMP 朝向 → viewer 初始视角 ``(yaw, pitch, fov)``，单位度。

    yaw 以「原图水平中心」为 0：

    - 同时有 ``InitialViewHeadingDegrees``（初始视角的罗盘朝向）与
      ``PoseHeadingDegrees``（原图中心的罗盘朝向）时取两者之差——即初始视角
      相对原图中心偏了多少；
    - 只有 InitialView 信息时直接用它；两者都缺 → 0（正对原图中心，
      与在 DJI App 里打开这张图看到的一致）；
    - pitch / fov 有就用，缺省 0° / 100°，并夹到合理区间（防坏值把画面拉爆）。
    """
    if meta.initial_heading is not None and meta.heading_degrees is not None:
        yaw = _normalize_degrees(meta.initial_heading - meta.heading_degrees)
    elif meta.initial_heading is not None:
        yaw = _normalize_degrees(meta.initial_heading)
    else:
        yaw = 0.0

    pitch = meta.initial_pitch if meta.initial_pitch is not None else 0.0
    fov = meta.initial_fov if meta.initial_fov is not None else DEFAULT_FOV_DEGREES
    return (
        round(yaw, 3),
        round(max(-MAX_PITCH_DEGREES, min(MAX_PITCH_DEGREES, pitch)), 3),
        round(max(MIN_FOV_DEGREES, min(MAX_FOV_DEGREES, fov)), 3),
    )
