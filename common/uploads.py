"""上传文件的安全校验：按真实内容判定类型，由服务端决定扩展名。

**为什么必须在这里拦**：客户端给的 ``Content-Type`` 和文件名扩展名都不可信。
公开媒体目录（``MEDIA_ROOT``）由 nginx 按**扩展名**直出，一旦落下 ``.html`` /
``.svg`` / ``.xml`` 这类浏览器会当文档执行的扩展名，就等于在站点同源托管了任意
脚本——存储型 XSS（可读 CSRFToken、以受害者身份调用 API）。

三道闸门：
1. 扩展名黑名单 ``RESTRICTED_EXTENSIONS``：命中即拒（不赌客户端诚实）；
2. 图片走 Pillow 真实解码（``sniff_image_extension``）：格式由内容决定，
   落盘扩展名由本模块给出，客户端写的 ``.html`` 不可能留下；
3. PDF 走 ``%PDF-`` magic 校验（``sniff_pdf``）。

非图片/PDF 的普通附件（docx、zip、txt…）由 ``upload_error`` 用扩展名白名单 +
黑名单双查；它们落盘后不会被执行，风险等级低于图片/文档直出。
"""
from __future__ import annotations

import os
import re

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

# 浏览器会当作文档/脚本解析的扩展名：绝不允许以这些后缀落到公开媒体目录。
RESTRICTED_EXTENSIONS = frozenset({
    # 文档 / 标记语言（同源执行脚本的载体）
    ".html", ".htm", ".xhtml", ".xht", ".shtml", ".shtm", ".html5", ".xhtml5",
    ".svg", ".svgz", ".xml", ".xsl", ".xslt", ".mhtml", ".mht", ".htaccess", ".htpasswd",
    # 脚本 / 样式
    ".js", ".mjs", ".cjs", ".json", ".jsonp", ".jsonx", ".css",
    # 服务端可执行
    ".php", ".php3", ".php4", ".php5", ".php7", ".php8", ".phtml", ".phtm", ".pht",
    ".phps", ".phar", ".inc", ".asp", ".aspx", ".jsp", ".jspx", ".war", ".cgi",
    # 本地可执行 / 动态库
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".msi", ".sh", ".bash", ".zsh",
    ".py", ".rb", ".pl", ".lua", ".go", ".vbs", ".wsf", ".jar", ".class", ".so", ".dll",
})

# Pillow 识别出的格式 → 我们允许落盘的扩展名（只保留浏览器当图片处理的四种）。
IMAGE_EXT_BY_FORMAT = {
    "JPEG": ".jpg",
    "MPO": ".jpg",   # JPEG 多图（部分手机直出），按 jpg 处理
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
}
DEFAULT_IMAGE_EXTENSIONS = frozenset(IMAGE_EXT_BY_FORMAT.values())


def extension_of(name: str | None) -> str:
    """取小写扩展名（含点）；无扩展名返回空串。"""
    return os.path.splitext(name or "")[1].lower()


def is_restricted(name: str | None) -> bool:
    """文件名扩展名是否属于「浏览器会执行」的集合。"""
    return extension_of(name) in RESTRICTED_EXTENSIONS


def _safe_stem(name: str | None, fallback: str = "upload") -> str:
    """文件名主干清洗：去路径分隔符与控制字符，限长（防止超长怪异名）。"""
    stem = os.path.splitext(os.path.basename(name or ""))[0] or fallback
    cleaned = "".join(ch for ch in stem if ch.isprintable() and ch not in '\\/:*?"<>|').strip()
    return (cleaned or fallback)[:80]


def rename_upload(file, ext: str):
    """把上传对象的文件名改成「主干 + 服务端决定的扩展名」，并返回该对象。

    保存前调用它，``upload_to`` 里取的扩展名就完全由服务端控制。
    """
    filename = getattr(file, "name", None) or "upload"
    file.name = _safe_stem(filename) + ext
    return file


def sniff_image_extension(file, allowed: frozenset[str] | set[str] | None = None) -> str:
    """用 Pillow 真实解码，返回规范扩展名；不是合法图片则抛 ``ValidationError``。

    ``allowed`` 可再收窄（例如头像只收 JPG/PNG/GIF/WebP）。判定依据是文件内容，
    与客户端声称的 ``content_type``、文件名后缀无关。
    """
    allowed = frozenset(allowed) if allowed else DEFAULT_IMAGE_EXTENSIONS
    try:
        file.seek(0)
    except (AttributeError, OSError, ValueError):
        pass
    fmt = ""
    try:
        with Image.open(file) as image:
            fmt = (image.format or "").upper()
            image.verify()  # 真正解析结构：伪造的 txt/html 声明成图片会在这里炸
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ValidationError("文件内容不是有效的图片，请重新选择。") from exc
    except Exception as exc:  # Pillow 的 DecompressionBomb 等异常
        raise ValidationError("图片无法解析，请换一张试试。") from exc
    finally:
        try:
            file.seek(0)
        except (AttributeError, OSError, ValueError):
            pass

    ext = IMAGE_EXT_BY_FORMAT.get(fmt)
    if not ext or ext not in allowed:
        raise ValidationError("仅支持 JPG、PNG、GIF、WebP 图片。")
    return ext


PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


def safe_extension(name: str | None, default: str = ".bin") -> str:
    """落盘用的扩展名：黑名单/空/格式异常一律退回 ``default``（.bin 不会被浏览器执行）。

    这是**落盘层的兜底**：即使某个视图忘了做真实内容校验，文件也不会以 .html /
    .svg 之类落到公开媒体目录。正常路径（视图已按内容改写扩展名）不受影响。
    """
    ext = extension_of(name)
    if not ext or len(ext) > 11 or not re.fullmatch(r"\.[a-z0-9]+", ext):
        return default
    if ext in RESTRICTED_EXTENSIONS:
        return default
    return ext


def sniff_pdf(file) -> bool:
    """判断文件是否是 PDF（读前 5 字节的 magic）。会恢复文件指针。"""
    return _sniff_magic(file, PDF_MAGIC)


def sniff_zip(file) -> bool:
    """判断文件是否是 ZIP 容器（.docx / .xlsx 的基本形态）。会恢复文件指针。"""
    return _sniff_magic(file, ZIP_MAGIC)


def _sniff_magic(file, magic: bytes) -> bool:
    try:
        file.seek(0)
        head = file.read(len(magic))
    except (AttributeError, OSError, ValueError):
        return False
    finally:
        try:
            file.seek(0)
        except (AttributeError, OSError, ValueError):
            pass
    return head == magic
