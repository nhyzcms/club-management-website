"""本版本的发行说明，给前端「更新了什么」弹窗用。

两种来源，按可靠性排序：

1. ``changelog.json`` —— CI 在构建镜像前由 ``scripts/gen_changelog.py`` 生成，
   随镜像分发。生产走这条。
2. ``CHANGELOG.md`` —— 本地开发没有构建产物，直接解析仓库里的 Markdown 兜底。
   两边用的是同一个解析函数，所以本地看到的内容和线上不会分叉。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .changelog_parse import parse_entry
from .version import build_info


def _json_path() -> Path:
    configured = getattr(settings, "CHANGELOG_JSON_PATH", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "changelog.json"


def _markdown_path() -> Path:
    return Path(settings.BASE_DIR) / "CHANGELOG.md"


@lru_cache(maxsize=1)
def changelog_entry() -> dict | None:
    """当前版本的发行说明；查不到返回 None（前端据此不弹窗）。"""
    path = _json_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("sections"):
            return data

    md = _markdown_path()
    if md.is_file():
        try:
            return parse_entry(md.read_text(encoding="utf-8"), build_info()["base_version"])
        except OSError:
            return None
    return None
