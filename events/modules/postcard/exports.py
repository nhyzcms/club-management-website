"""明信片登记导出：Excel（openpyxl）与 PDF（reportlab + NotoSansSC）。

- 行粒度 = **每张明信片（条目）**，登记单信息按列重复——既能按登记码筛出
  一单，也能直接当签收清单用；
- **Excel 公式注入防护**：导出内容含访客填写的姓名/校名，`= + - @ \\t \\r`
  开头的单元格前置 `'` 强制按文本（同 ``activities/survey_export.py`` 审计 M-5）；
- PDF 中文：NotoSansSC（``barcode.noto_font()`` 共享注册），缺字体时退化
  Helvetica 并把中文列转拼音占位——生产字体在仓库内，正常不会走到退化。
- 两个入口都仅管理员可达，且调用方必须落审计日志。
"""
from __future__ import annotations

import io
from datetime import datetime

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .barcode import noto_font
from .models import PostcardItem, PostcardRegistration

#: 导出列（Excel 与 PDF 共用定义）。
COLUMNS = ["登记码", "寄出人", "年级", "班级", "寄达区", "寄达校", "条码号", "条目状态", "登记单状态", "登记时间"]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value) -> str:
    """公式注入防护：危险前缀前置单引号（Excel 强制按文本）。"""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _rows(qs) -> list[list[str]]:
    """条目 queryset → 导出行（select_related 由调用方保证）。"""
    status_labels = dict(PostcardRegistration.STATUS_CHOICES)
    rows = []
    for item in qs:
        reg = item.registration
        rows.append([
            reg.reg_code,
            reg.sender_name,
            reg.grade_label,
            f"{reg.class_no}班",
            reg.dest_region,
            reg.dest_school,
            item.barcode.code,
            status_labels.get(item.status, item.status),
            status_labels.get(reg.status, reg.status),
            reg.created_at.strftime("%Y-%m-%d %H:%M") if reg.created_at else "",
        ])
    return rows


def _filtered_items(event, params):
    """按管理端搜索参数取条目（与记录列表同一套过滤逻辑的导出版）。"""
    from .views import _admin_items_queryset  # 延迟 import 避免环

    return _admin_items_queryset(event, params)


def export_xlsx(event, params, title: str = "") -> HttpResponse:
    qs = _filtered_items(event, params)
    wb = Workbook()
    ws = wb.active
    ws.title = "明信片登记"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for row in _rows(qs):
        ws.append([_cell(v) for v in row])

    widths = [10, 12, 8, 8, 14, 24, 10, 10, 12, 17]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    resp["Content-Disposition"] = f'attachment; filename="postcard-records-{stamp}.xlsx"'
    return resp


def export_pdf(event, params, title: str = "") -> HttpResponse:
    qs = _filtered_items(event, params)
    font = noto_font()
    base = font or "Helvetica"
    style = ParagraphStyle(
        "cell", fontName=base, fontSize=8, leading=11,
    )
    head_style = ParagraphStyle(
        "head", parent=style, fontName=base, fontSize=9, leading=12,
        textColor=colors.white,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"明信片登记导出 · {title or event.title}",
    )
    story = [Paragraph(f"明信片登记导出 · {title or event.title}", ParagraphStyle(
        "title", fontName=base, fontSize=13, leading=18,
    )), Spacer(1, 4 * mm)]

    data = [[Paragraph(c, head_style) for c in COLUMNS]]
    for row in _rows(qs):
        data.append([Paragraph(_cell(v), style) for v in row])

    table = Table(
        data, repeatRows=1,
        colWidths=[16 * mm, 18 * mm, 12 * mm, 12 * mm, 22 * mm, 40 * mm, 16 * mm, 16 * mm, 18 * mm, 24 * mm],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FC")]),
    ]))
    story.append(table)
    doc.build(story)

    resp = HttpResponse(content_type="application/pdf")
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    resp["Content-Disposition"] = f'attachment; filename="postcard-records-{stamp}.pdf"'
    resp.write(buf.getvalue())
    return resp
