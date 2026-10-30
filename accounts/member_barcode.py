"""条形码渲染与批量导出（社员身份编号系统，见 ADR-0025）。

工牌产物与二维码互补：二维码承载**带签名的校验 URL**（扫码即查），
条形码承载**短签名载荷**（手机摄像头扫码 / 扫码枪 / 手工输入查询）。

**载荷 = 12 位数字**：``6 位唯一键 + 6 位十进制短签名``（见 ``member_codes.barcode_payload``）。
条码下方人眼可读行仍是 8 位识别码。长度是硬约束——Code128C 每 2 位数字 11 模块，
12 位 = 101 模块（0.254mm/模块时含静区 30.7mm）；16 位 hex 签名会撑到 255 模块且掉回
Code128B，宽度翻倍，所以签名必须是纯数字。

**硬边界：条形码不是链接载体。** 2026-10-19 微信实测——扫 Code128 只会显示数字、
不打开网页；把校验链接编进条码（596 模块 / 300dpi 约 104 mm 宽）后微信无法识别。
「扫码打开校验页」一律用二维码（``/#/v/<码>?s=<签名>``）。

- 编码：``reportlab`` 的 Code128 实现（站内已有依赖）；
- 栅格渲染：``Pillow`` 按模块宽度画条（零新依赖；reportlab 的 renderPM 需要
  rlPyCairo 后端，不为单一导出引入）；
- 矢量渲染：纯字符串拼 SVG（零新依赖），**背景透明**——不画底色矩形，
  条与字之间的空隙露出承印物的底色；几何与 PNG 同构（1 用户单位 = 1 模块），
  ``width`` / ``height`` 按 400dpi 折算成毫米，放进印刷版面可无损缩放；
- 单码 ``render_png``：module 4px / 条高 60px / 左右静区 10 模块 /
  下方印识别码文字（DejaVuSans，缺字体退化为纯条码）；
- 单码 ``render_svg``：同一几何的矢量版，人眼可读行是 ``<text>``（字体缺失时
  浏览器按 ``font-family`` 回退，居中靠 ``text-anchor="middle"``，不会跑位）；
- ``export_zip`` / ``export_svg_zip``：批量导出 ZIP，文件名 ``识别码_姓名.png|svg``
  （与二维码导出一致）。
"""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

from .member_codes import barcode_payload
from .member_qr import _safe_name

MODULE_PX = 4
BAR_PX = 60
QUIET_MODULES = 10
TEXT_PX = 28
TEXT_PAD_PX = 2
FONT_PX = 22
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
# PNG 的印刷基准：module 4px ≙ 0.254mm（Code128 常用 X 尺寸下限）= 400dpi。
DPI = 400
# 条码是纯数字 + 纯黑，字体只影响字形风格；回退链保证缺字体时仍是等宽观感的无衬线。
SVG_FONT_FAMILY = "'DejaVu Sans', 'Liberation Sans', Helvetica, Arial, sans-serif"


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


def _runs(pattern: str) -> list[tuple[bool, int]]:
    """字母宽度序列 → ``[(是否黑条, 模块数), ...]``。"""
    return [(ch.isupper(), ord(ch.upper()) - ord("A") + 1) for ch in pattern]


def _load_font():
    try:
        return ImageFont.truetype(_FONT_PATH, FONT_PX)
    except OSError:
        return ImageFont.load_default()


def _text_ascent() -> int:
    """字体上沿到基线的距离（px）。缺字体 / 无度量 API 时按 0.8em 估。"""
    try:
        metrics = getattr(_load_font(), "getmetrics")
        return int(metrics()[0])
    except Exception:  # noqa: BLE001 —— 量字体高度失败不该拖垮整张图
        return int(FONT_PX * 0.8)


def _num(value: float) -> str:
    """数字写进 SVG 属性：去掉浮点尾巴（15.0 → 15，5.5 → 5.5）。"""
    text = f"{round(value, 4):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def render_png(code: str, *, module_px: int = MODULE_PX) -> bytes:
    """渲染单张 Code128 条形码 PNG（白底黑条，打印友好）。

    条码内容是 12 位签名载荷；下方印人眼可读的 8 位识别码。
    """
    if not code:
        raise ValueError("识别码不能为空")
    _, pattern = _encode(barcode_payload(code))
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
        draw.text(((width - text_w) / 2, BAR_PX + TEXT_PAD_PX), code, fill="black", font=font)
    except Exception:  # 极端字体退化：左对齐纯文本，绝不因文字渲染失败丢整张图
        draw.text((QUIET_MODULES * module_px, BAR_PX + TEXT_PAD_PX), code, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_svg(code: str, *, show_text: bool = True) -> str:
    """渲染单张 Code128 条形码 SVG（矢量、**背景透明**）。

    几何与 PNG 完全同构，但坐标用「模块」而不是像素：1 用户单位 = 1 模块，
    ``viewBox`` 因此与 DPI 无关；``width`` / ``height`` 另按 400dpi 折算成毫米
    （模块 4px ≙ 0.254mm），放进工牌／海报版面时尺寸就是印刷尺寸，缩放不糊。

    **不画任何底色矩形**——条间的空隙就是画布本身，叠在工牌底色上时露出来的
    是承印物（纸张 / 卡片 / 背景色），而不是一块白板。需要白底请由调用方在
    版面里垫一层，或在 ``<g>`` 下面自己加 ``<rect fill="#fff">``。
    """
    if not code:
        raise ValueError("识别码不能为空")
    _, pattern = _encode(barcode_payload(code))
    runs = _runs(pattern)
    total_modules = sum(w for _, w in runs)
    width_modules = total_modules + 2 * QUIET_MODULES
    bar_height = BAR_PX / MODULE_PX
    height_modules = bar_height + (TEXT_PX / MODULE_PX if show_text else 0)
    width_mm = width_modules * MODULE_PX / DPI * 25.4
    height_mm = height_modules * MODULE_PX / DPI * 25.4

    # 黑条：只用 <rect> 拼前景，没有任何铺满画布的矩形 → 背景天然透明。
    rects: list[str] = []
    x = QUIET_MODULES
    for is_bar, modules in runs:
        if is_bar:
            rects.append(
                f'<rect x="{x}" y="0" width="{modules}" '
                f'height="{_num(bar_height)}"/>'
            )
        x += modules

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{_num(width_mm)}mm" height="{_num(height_mm)}mm" '
            f'viewBox="0 0 {width_modules} {_num(height_modules)}" '
            f'role="img" aria-label="Code128 {escape(code)}">'
        ),
        f"<title>{escape(code)}</title>",
        "<!-- 背景透明：不绘制底色矩形，空隙露出承印物 -->",
        '<g fill="#000000" shape-rendering="crispEdges">',
        *rects,
        "</g>",
    ]
    if show_text:
        font_size = FONT_PX / MODULE_PX
        baseline = (BAR_PX + TEXT_PAD_PX + _text_ascent()) / MODULE_PX
        parts.append(
            f'<text x="{_num(width_modules / 2)}" y="{_num(baseline)}" '
            f'font-family="{SVG_FONT_FAMILY}" font-size="{_num(font_size)}" '
            f'fill="#000000" text-anchor="middle">{escape(code)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


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


def export_svg_zip(rows) -> bytes:
    """把名册行批量导出为**矢量**条形码 ZIP（``识别码_姓名.svg``，同名去重加序号）。"""
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            fname = f"{row.code}_{_safe_name(row.name)}.svg"
            if fname in used:
                fname = f"{row.code}_{_safe_name(row.name)}_{row.pk}.svg"
            used.add(fname)
            zf.writestr(fname, render_svg(row.code).encode("utf-8"))
    return buf.getvalue()
