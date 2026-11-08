"""明信片条码：批量生成 + A4 整版 PDF 导出（方案 docs/plans/postcard-exchange.md §4）。

- 条码号 = **7 位纯随机数字**（``secrets``），Code128 编码，单活动内唯一
  （DB 唯一约束兜底，生成时先排除存量）；
- 数量强校验：**1500 ~ 10000、步进 500**（默认 6000），单活动累计不超过 10000；
- PDF：A4 整版，条码规格 40×20mm（条 + 下方 7 位人眼可读数字），间隙 2mm，
  每页 5 列 × 13 行 = 65 枚；6000 张 ≈ 93 页。reportlab canvas 流式绘制，
  逐页输出，2C2G 服务器无压力。

Code128 几何与 ``accounts/member_barcode.py`` 同构（reportlab 编码 → 字母宽度
序列 → 画条），但本模块自持实现，不跨 app import 私有函数（modules 独立性约定）。
"""
from __future__ import annotations

import io
import secrets
from typing import Iterator

from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from .models import PostcardBarcode

#: 数量边界（含）与步进：1500~10000、步进 500、默认 6000。
COUNT_MIN = 1500
COUNT_MAX = 10000
COUNT_STEP = 500
COUNT_DEFAULT = 6000

#: 版面：条码 40×20mm、间隙 2mm → A4(210×297) 每页 5 列 × 13 行。
CELL_W = 40 * mm
CELL_H = 20 * mm
GAP = 2 * mm
COLS = 5
ROWS = 13
PER_PAGE = COLS * ROWS

#: Code128 静区（左右各 10 模块）与条内文字区。
QUIET_MODULES = 10
TEXT_AREA_H = 4.5 * mm

_NOTO = None
_NOTO_TRIED = False


def noto_font() -> str | None:
    """NotoSansSC 注册（PDF 中文用；条码数字是 ASCII，Helvetica 即可）。

    字体缺失时返回 None，调用方退化——绝不为一个页眉拖垮整份导出。
    包内共享（exports.py 复用）；结果进程级缓存。
    """
    global _NOTO, _NOTO_TRIED
    if _NOTO_TRIED:
        return _NOTO
    _NOTO_TRIED = True
    try:
        from django.conf import settings
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        path = settings.BASE_DIR / "activities" / "fonts" / "NotoSansSC.ttf"
        if path.exists():
            pdfmetrics.registerFont(TTFont("PostcardNoto", str(path)))
            _NOTO = "PostcardNoto"
    except Exception:  # noqa: BLE001
        _NOTO = None
    return _NOTO


def _encode(code: str) -> str:
    """Code128 编码 → reportlab 字母宽度序列（大写=黑条，序位=模块数）。"""
    from reportlab.graphics.barcode import code128

    bc = code128.Code128(code)
    bc.validate()
    bc.encode()
    return bc.decompose()


def _runs(pattern: str) -> list[tuple[bool, int]]:
    return [(ch.isupper(), ord(ch.upper()) - ord("A") + 1) for ch in pattern]


def validate_count(count: int) -> int:
    """数量强校验：1500~10000、步进 500。不合法抛 ValueError（中文文案）。"""
    try:
        count = int(count)
    except (TypeError, ValueError):
        raise ValueError("条码数量必须是整数")
    if count < COUNT_MIN or count > COUNT_MAX:
        raise ValueError(f"条码数量须在 {COUNT_MIN}~{COUNT_MAX} 之间")
    if count % COUNT_STEP != 0:
        raise ValueError(f"条码数量须为 {COUNT_STEP} 的倍数")
    return count


def generate_barcodes(event, count: int, replace: bool = False) -> list[PostcardBarcode]:
    """为活动生成 count 个不重复的 7 位条码（默认增量，``replace=True`` 覆盖重建）。

    - 增量（默认）：避开存量，累计 ≤ 10000；
    - 覆盖：先清空**尚未被登记占用**的条码，再按 count 重建（= 生成新区间）。
      已被 ``PostcardItem`` 绑定的条码受 ``PROTECT`` 保护，一条都不能删——此时
      直接拒绝并告知占用数量，避免把已发出去的明信片变成孤儿。

    7 位数字空间 10^7，万级取样的碰撞率极低，但仍以「批量抽样 → 排除存量 →
    补齐」循环保证唯一；DB 唯一约束是最后防线。
    """
    count = validate_count(count)
    existing_qs = PostcardBarcode.objects.filter(event=event)
    if replace:
        bound = existing_qs.filter(item__isnull=False).count()
        if bound:
            raise ValueError(
                f"已有 {bound} 个条码被登记占用，不能覆盖重建；请先处理这些登记"
            )
        existing_qs.delete()
        existing: set[str] = set()
    else:
        existing = set(existing_qs.values_list("code", flat=True))
        if len(existing) + count > COUNT_MAX:
            raise ValueError(
                f"本活动已有 {len(existing)} 个条码，累计不得超过 {COUNT_MAX}"
            )

    codes: set[str] = set()
    while len(codes) < count:
        need = count - len(codes)
        batch = {f"{secrets.randbelow(10_000_000):07d}" for _ in range(need)}
        batch -= existing
        batch -= codes
        codes |= batch

    rows = [PostcardBarcode(event=event, code=c) for c in sorted(codes)]
    PostcardBarcode.objects.bulk_create(rows, batch_size=1000)
    return rows


def _draw_code128(c: pdf_canvas.Canvas, code: str, x: float, y: float, w: float, h: float):
    """在 (x, y) 起的 w×h 盒内画一枚 Code128：条占上部，7 位数字居中在下部。"""
    pattern = _encode(code)
    runs = _runs(pattern)
    total_modules = sum(n for _, n in runs)
    bar_h = h - TEXT_AREA_H
    # 模块宽：把左右静区计入总宽，条码整体恰好铺满 40mm（含静区，扫描可靠）。
    unit = w / (total_modules + 2 * QUIET_MODULES)
    quiet_w = QUIET_MODULES * unit
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0, 0, 0)
    cx = x + quiet_w
    for black, n in runs:
        if black:
            c.rect(cx, y + TEXT_AREA_H, unit * n, bar_h, stroke=0, fill=1)
        cx += unit * n
    c.drawCentredString(x + w / 2, y + 1.2 * mm, code)


def _iter_pages(codes: Iterator[str]):
    """把条码流切成每页 65 个的页流。"""
    page: list[str] = []
    for code in codes:
        page.append(code)
        if len(page) == PER_PAGE:
            yield page
            page = []
    if page:
        yield page


def export_pdf(event, title: str = "") -> HttpResponse:
    """整版导出条码 PDF：流式 HttpResponse（不落盘、不缓存全量字节）。"""
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    grid_w = COLS * CELL_W + (COLS - 1) * GAP
    grid_h = ROWS * CELL_H + (ROWS - 1) * GAP
    margin_x = (page_w - grid_w) / 2
    margin_y = (page_h - grid_h) / 2

    noto = noto_font()
    codes = (
        PostcardBarcode.objects.filter(event=event)
        .order_by("code")
        .values_list("code", flat=True)
        .iterator(chunk_size=1000)
    )
    total = PostcardBarcode.objects.filter(event=event).count()
    page_no = 0
    for page in _iter_pages(iter(codes)):
        page_no += 1
        # 页眉画在上边距里（6.5mm 高，6pt 字够用）。
        if noto:
            c.setFont(noto, 6)
        else:
            c.setFont("Helvetica", 6)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        header = title or f"活动 #{event.pk}"
        c.drawString(margin_x, page_h - margin_y + 1.5 * mm, f"{header} · 明信片条码")
        c.drawRightString(
            page_w - margin_x, page_h - margin_y + 1.5 * mm,
            f"第 {page_no} 页 · 共 {(total + PER_PAGE - 1) // PER_PAGE} 页",
        )
        for i, code in enumerate(page):
            col, row = i % COLS, i // COLS
            x = margin_x + col * (CELL_W + GAP)
            y = page_h - margin_y - (row + 1) * CELL_H - row * GAP
            _draw_code128(c, code, x, y, CELL_W, CELL_H)
        # 页脚打印提示：5 列 40mm 撑满 A4 横向，缩放打印会把条码裁掉/变窄。
        c.setFillColorRGB(0.45, 0.45, 0.45)
        if noto:
            c.setFont(noto, 6)
            c.drawCentredString(
                page_w / 2, margin_y - 4.5 * mm,
                "打印提示：请选择「实际大小 / 100%」，勿缩放；条码 40×20mm，间隙 2mm 供裁切",
            )
        else:
            c.setFont("Helvetica", 6)
            c.drawCentredString(
                page_w / 2, margin_y - 4.5 * mm,
                "Print at 100% (actual size): barcode 40x20mm, 2mm gap",
            )
        c.showPage()

    if page_no == 0:
        # 没有条码也输出一页说明，避免空 PDF 被阅读器误判损坏。
        c.setFont("Helvetica", 12)
        c.drawCentredString(page_w / 2, page_h / 2, "No barcodes generated yet.")
        c.showPage()
    c.save()

    resp = HttpResponse(content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="postcard-barcodes-{event.pk}.pdf"'
    resp.write(buf.getvalue())
    return resp
