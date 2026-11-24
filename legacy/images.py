"""旧浏览器也能看的图片兜底。

WebP / AVIF 这类格式现代浏览器直接就能显示，IE 全系（含 IE11）不能。
为了不让现代浏览器被一起拖回 JPEG，页面里用 <picture>：

    <picture>
      <source type="image/webp" srcset="/media/x.webp">
      <img src="/legacy/img/<token>.jpg" alt="">
    </picture>

- 能解 WebP 的浏览器走 <source>，看到原图；
- 解不了的浏览器（IE8–IE11、老 Safari 等）忽略 <picture>/<source>，
  落到 <img>，看到这里生成的 JPEG 兜底图；
- 两样都做不到（SVG / HEIC 之类转不了）才退回文字说明。

兜底图第一次用到时用 Pillow 转一份，存 CLUB_DATA_DIR/legacy-cache/<token>.jpg，
之后直接读文件。token 里带了源文件的 mtime 与大小，源图换了 token 就变，
不会把旧图缓存到天荒地老。
"""

import hashlib
import os
import re
import tempfile
import threading
from pathlib import Path

from django.conf import settings

# IE8 及更早版本解不了的图片格式（和 queries / sanitize 共用同一份判断）。
UNSUPPORTED_EXTS = (".webp", ".avif", ".svg", ".heic", ".heif")

# 源图上限：超过就不转（避免拿一张 80MB 的图把 2 核小机器拖死）。
MAX_SOURCE_BYTES = 24 * 1024 * 1024
# 像素上限：字节数小不代表不吃内存——12000x12000 的 WebP 只有几百 KB，
# 解码却要 ~2.3GB（实测）。转码发生在请求线程里，生产默认单 worker，
# 一张这样的图就能把整站打 OOM，所以先看像素、再看字节。
# 阈值与 news.thumbnails.MAX_COVER_PIXELS 对齐。
MAX_PIXELS = 40_000_000
# 输出最长边与质量：旧浏览器窗口普遍不大，1600px 已经够用。
MAX_EDGE = 1600
JPEG_QUALITY = 82
CACHE_KEEP = 400

# <picture><source type> 的取值：浏览器据此决定用不用这张图。
SOURCE_TYPES = {
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
    ".heic": "image/heic",
    ".heif": "image/heif",
}

TOKEN_RE = re.compile(r"^[0-9a-f]{40}$")
_LOCK = threading.Lock()


def cache_dir():
    return Path(settings.DATA_DIR) / "legacy-cache"


def needs_fallback(path):
    name = (path or "").split("?", 1)[0].lower()
    return name.endswith(UNSUPPORTED_EXTS)


def source_type(path):
    """图片路径 → MIME；认不出的返回空串。"""
    name = (path or "").split("?", 1)[0].lower()
    for ext, mime in SOURCE_TYPES.items():
        if name.endswith(ext):
            return mime
    return ""


def variant_url(token):
    return "/legacy/img/" + token + ".jpg"


def _cache_file(token):
    return cache_dir() / (token + ".jpg")


def _source_path(url_path):
    """站内图片 URL → MEDIA_ROOT 下的真实文件；越界 / 不存在返回 None。"""
    media_url = settings.MEDIA_URL or "/media/"
    path = (url_path or "").split("?", 1)[0]
    if not path.startswith(media_url):
        return None
    rel = path[len(media_url):].lstrip("/")
    if not rel or "\\" in rel or ".." in rel.split("/"):
        return None
    root = Path(settings.MEDIA_ROOT).resolve()
    try:
        source = (root / rel).resolve()
        source.relative_to(root)
    except (OSError, ValueError):
        return None
    return source if source.is_file() else None


def _token_for(rel, stat_result):
    raw = "%s|%d|%d" % (rel, int(stat_result.st_mtime), int(stat_result.st_size))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _prune():
    """缓存目录别无限长：超过 CACHE_KEEP 张就按修改时间删掉最旧的一批。"""
    try:
        files = sorted(cache_dir().glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for old in files[: max(0, len(files) - CACHE_KEEP)]:
        try:
            old.unlink()
        except OSError:
            pass


def _convert(source, target):
    """把任意 Pillow 能读的图转成 JPEG。转不了（SVG / 坏文件）返回 False。"""
    try:
        from PIL import Image
    except ImportError:
        return False
    tmp = None
    try:
        with Image.open(source) as img:
            # 先看像素再看像素内容：load() 之前判，解码炸弹到不了内存。
            if img.width * img.height > MAX_PIXELS:
                return False
            img.load()
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                img = flat
            else:
                img = img.convert("RGB")
            img.thumbnail((MAX_EDGE, MAX_EDGE))
            # 临时名必须唯一：多 worker 会同时对同一张源图首次转码，
            # 固定叫 <token>.tmp 时两边会互相覆写（Windows 直接一方失败，
            # Linux 上可能产出半截 JPEG 然后被 max-age 长期缓存）。
            fd, tmp = tempfile.mkstemp(dir=str(cache_dir()), suffix=".tmp")
            os.close(fd)
            os.chmod(tmp, 0o644)
            img.save(tmp, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    except Exception:
        # Pillow 抛的异常类型很多（UnidentifiedImageError / OSError /
        # DecompressionBombError…），这里只关心「没转成」，不该把页面打 500。
        _discard(tmp)
        return False
    try:
        os.replace(tmp, str(target))
    except OSError:
        _discard(tmp)
        return False
    return True


def _discard(path):
    """删掉转码中途的临时文件；没建成就什么也不做。"""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def fallback_url(url_path):
    """站内图片路径 → 兜底 JPEG 的站内 URL；做不了兜底返回空串。

    只处理 MEDIA_ROOT 下的本地文件：对象存储 / 外链不转，也不代理。
    """
    source = _source_path(url_path)
    if source is None:
        return ""
    try:
        stat_result = source.stat()
    except OSError:
        return ""
    if stat_result.st_size <= 0 or stat_result.st_size > MAX_SOURCE_BYTES:
        return ""
    rel = str(source.relative_to(Path(settings.MEDIA_ROOT).resolve())).replace(os.sep, "/")
    token = _token_for(rel, stat_result)
    target = _cache_file(token)
    if target.is_file():
        return variant_url(token)
    with _LOCK:
        if target.is_file():
            return variant_url(token)
        try:
            cache_dir().mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""
        if not _convert(source, target):
            return ""
        _prune()
    return variant_url(token)


def fallback_file(token):
    """兜底图的真实路径（给视图用）；token 非法 / 文件不存在返回 None。"""
    if not TOKEN_RE.match(token or ""):
        return None
    path = _cache_file(token)
    return path if path.is_file() else None
