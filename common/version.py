"""版本快照：镜像里读 CI 写入的 ``build_info.json``，本地开发回落到包元数据。

版本号不靠人维护——``.github/workflows/image.yml`` 在构建镜像前调用
``scripts/gen-build-info.sh`` 生成这个文件。人会忘记改版本号，机器不会。

为什么不在构建时改 ``pyproject.toml``：
版本号一旦被 workflow 改写并提交，每个分支都要处理一次冲突；而 ``build_info.json``
只存在于构建上下文里，不进仓库，也就不进任何人的 diff。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings

UNKNOWN = "0.0.0+unknown"


def _path() -> Path:
    """构建信息文件位置。默认在项目根目录，测试可经 settings 改写。"""
    configured = getattr(settings, "BUILD_INFO_PATH", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "build_info.json"


def _fallback_version() -> str:
    """没有构建信息（本地开发、纯源码运行）时，用已安装包的元数据。"""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python < 3.8 才有
        return UNKNOWN
    for dist in ("backend", "club-management-website"):
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return UNKNOWN


@lru_cache(maxsize=1)
def build_info() -> dict:
    """返回版本快照。字段固定，调用方不必判空。"""
    path = _path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict) and raw.get("version"):
            tag = raw.get("tag")
            return {
                "version": str(raw["version"]),
                "base_version": str(raw.get("base_version") or raw["version"]),
                "channel": str(raw.get("channel") or "dev"),
                "tag": str(tag) if tag else None,
                "commit": str(raw.get("commit") or ""),
                "commit_short": str(raw.get("commit_short") or ""),
                "commits_since_tag": raw.get("commits_since_tag"),
                "built_at": str(raw.get("built_at") or ""),
                "built_by": str(raw.get("built_by") or ""),
                "source": path.name,
            }

    return {
        "version": _fallback_version(),
        "base_version": _fallback_version(),
        "channel": "dev",
        "tag": None,
        "commit": "",
        "commit_short": "",
        "commits_since_tag": None,
        "built_at": "",
        "built_by": "",
        "source": "pyproject",
    }


def version_string() -> str:
    """一行版本号，写日志、打 banner 用。"""
    info = build_info()
    commit = info["commit_short"]
    return f"{info['version']} ({commit})" if commit else info["version"]
