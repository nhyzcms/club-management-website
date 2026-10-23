"""条形码渲染与批量导出（社员身份编号系统，见 ADR-0025）。

工牌产物与二维码互补：二维码承载**带签名的校验 URL**（扫码即查），
条形码承载**裸识别码**（扫码枪 / 手工输入到后台检索用）。

**硬边界：条形码不是链接载体。** 2026-10-19 微信实测——扫 Code128 只会显示数字、
不打开网页；把校验链接编进条码（596 模块 / 300dpi 约 104 mm 宽）后微信无法识别。
「扫码打开校验页」一律用二维码（``/#/v/<码>?s=<签名>``）。

- 编码：``reportlab`` 的 Code128 实现（站内已有依赖；8 位数字自动走
  Code128C：START + 4 个数字对 + 校验位 + STOP，共 79 模块）；
- 渲染：``Pillow`` 按模块宽度画条（零新依赖；reportlab 的 renderPM 需要
  rlPyCairo 后端，不为单一导出引入）；
- 单码 ``render_png``：module 4px / 条高 60px / 左右静区 10 模块 /
  下方印识别码文字（DejaVuSans，缺字体退化为纯条码）；
- ``export_zip``：批量导出 ZIP，文件名 ``识别码_姓名.png``（与二维码导出一致）。
"""
from __future__ import annotations

import io
import zipfile

from PIL import Image, ImageDraw, ImageFont

from .member_qr import _safe_name

MODULE_PX = 4
BAR_PX = 60
QUIET_MODULES = 10
TEXT_PX = 28
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _encode(code: str) -> tuple[list[int], str]:
    """用 reportlab 编码：返回 (符号值序列, 字母宽度序列)。

    字母宽度序列中**大写 = 黑条、小写 = 空白**，字母序位 = 模块数
    （a/A = 1 模块，d/D = 4 模块）——即 reportlab ``_patterns`` 的原始形态。
    """
    from reportlab.graphics.barcode import code128

    bc = code128.Code128(code)
    bc.validate()
    bc.encode()
    return list(bc.encoded), bc.decompose()


def _load_font():
    try:
        return ImageFont.truetype(_FONT_PATH, 22)
    except OSError:
        return ImageFont.load_default()


def render_png(code: str, *, module_px: int = MODULE_PX) -> bytes:
    """渲染单张 Code128 条形码 PNG（白底黑条，打印友好）。"""
    if not code:
        raise ValueError("识别码不能为空")
    _, pattern = _encode(code)
    total_modules = sum(ord(ch.upper()) - ord("A") + 1 for ch in pattern)
    width = (total_modules + 2 * QUIET_MODULES) * module_px
    height = BAR_PX + TEXT_PX
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    x = QUIET_MODULES * module_px
    for ch in pattern:
        w = (ord(ch.upper()) - ord("A") + 1) * module_px
        if ch.isupper():
            draw.rectangle([x, 0, x + w - 1, BAR_PX - 1], fill="black")
        x += w
    font = _load_font()
    try:
        bbox = draw.textbbox((0, 0), code, font=font)
        text_w = bbox[2] - bbox[0]
        draw.text(((width - text_w) / 2, BAR_PX + 2), code, fill="black", font=font)
    except Exception:  # 极端字体退化：左对齐纯文本，绝不因文字渲染失败丢整张图
        draw.text((QUIET_MODULES * module_px, BAR_PX + 2), code, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def export_zip(rows) -> bytes:
    """把名册行批量导出为条形码 ZIP（文件名 ``识别码_姓名.png``，同名去重加序号）。"""
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            fname = f"{row.code}_{_safe_name(row.name)}.png"
            if fname in used:
                fname = f"{row.code}_{_safe_name(row.name)}_{row.pk}.png"
            used.add(fname)
            zf.writestr(fname, render_png(row.code))
    return buf.getvalue()
