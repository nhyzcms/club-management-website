"""二维码渲染与批量导出（社员身份编号系统，见 ADR-0025）。

- PNG 生成用 ``segno``（纯 Python、无额外依赖）；
- 单码 ``render_png``：目标边长约 512px（按模块数取整，实际略有出入）；
- ``export_zip``：批量导出 ZIP，文件名 ``识别码_姓名.png``（同名去重加序号）。
"""
from __future__ import annotations

import io
import re
import zipfile

from .member_codes import build_verify_url

TARGET_PX = 512
_BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


def render_png(code: str, *, target_px: int = TARGET_PX) -> bytes:
    import segno

    qr = segno.make(build_verify_url(code), error="m")
    base = qr.symbol_size(scale=1, border=2)[0]
    scale = max(1, target_px // base)
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()


def _safe_name(name: str) -> str:
    cleaned = _BAD_NAME_CHARS.sub("_", (name or "").strip())
    return cleaned or "未命名"


def export_zip(rows) -> bytes:
    """把名册行批量导出为二维码 ZIP（在内存中生成，俱乐部量级同步即可）。"""
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
