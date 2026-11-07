"""明信片照片安全管线（方案 docs/plans/postcard-exchange.md §5「文件上传」行）。

上传的「照片」是全站最不可信的输入（任何访客、活动期间开放），五道闸：

1. **大小上限**：原始上传 ≤5MB（超限直接拒，不读进内存再判）；
2. **魔数校验**：只认 JPEG / PNG / WebP 三种文件头，扩展名与 Content-Type
   一律不信（防伪装成图片的 HTML/脚本/Polyglot）；
3. **解码炸弹守卫**：``Image.open`` 是惰性的，先读 size 再解码——任一边
   >8000px 或总像素 >4000 万直接拒；
4. **重编码**：统一 ``thumbnail`` 到最长边 2048 后重编码 JPEG——EXIF（含
   GPS 定位）在重编码中天然剥离，任何内嵌 payload（注释段/缩略图藏毒）一并
   消灭；输出是服务端亲手生成的干净字节；
5. **私有存储**：落 ``PRIVATE_MEDIA_ROOT``，绝不经公开 MEDIA_URL 暴露，
   只经鉴权视图（本人出示登记码 / 复核权限）下发。

删除生命周期（通过即删 / 失败关标签页删 / 活动结束全删）在 PR2 接 AI 后
由 ``lifecycle`` 侧收口；本模块只提供 ``purge_photo`` 原语。
"""
from __future__ import annotations

import io

from django.core.files.base import ContentFile
from PIL import Image

#: 原始上传上限（字节）。
MAX_RAW_BYTES = 5 * 1024 * 1024
#: 重编码后最长边（px）。
MAX_EDGE = 2048
#: 解码炸弹守卫：单边 / 总像素上限（解码前判定）。
BOMB_EDGE = 8000
BOMB_PIXELS = 40_000_000
#: 重编码 JPEG 质量。
JPEG_QUALITY = 85

#: 魔数表：{前缀: 名称}。WebP 是 "RIFF....WEBP"（第 8-12 字节）。
_MAGIC = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
}


def _sniff_magic(head: bytes) -> str | None:
    for prefix, name in _MAGIC.items():
        if head.startswith(prefix):
            return name
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


class PhotoRejected(Exception):
    """照片被拒（文案面向用户，不泄露内部细节）。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_and_reencode(uploaded) -> ContentFile:
    """校验 + 重编码：返回干净的 JPEG ContentFile（EXIF 已剥离）。

    任何一步失败抛 ``PhotoRejected``（用户可读文案）；绝不把原始字节落盘。
    """
    raw = uploaded.read(MAX_RAW_BYTES + 1)
    if len(raw) > MAX_RAW_BYTES:
        raise PhotoRejected("照片超过 5MB 上限，请压缩后重试")
    if not raw:
        raise PhotoRejected("照片内容为空")

    kind = _sniff_magic(raw[:16])
    if kind is None:
        raise PhotoRejected("仅支持 JPEG / PNG / WebP 格式的照片")

    try:
        # 惰性打开：先拿 size 判炸弹，verify 查结构，再真正解码。
        probe = Image.open(io.BytesIO(raw))
        w, h = probe.size
        if max(w, h) > BOMB_EDGE or w * h > BOMB_PIXELS:
            raise PhotoRejected("照片尺寸过大")
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    except PhotoRejected:
        raise
    except Exception:  # noqa: BLE001 —— 解码失败统一文案，不回显内部异常
        raise PhotoRejected("照片无法解析，请换一张重试")

    return ContentFile(buf.getvalue(), name="photo.jpg")


def purge_photo(photo) -> None:
    """删除照片物理文件（行由调用方决定去留）。失败静默——清理不拖垮主流程。"""
    photo.delete_file()
