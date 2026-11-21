#!/usr/bin/env python3
"""把 CHANGELOG.md 里「当前版本」那一节转成前端能直接用的 JSON。

为什么要有这一步：CHANGELOG.md 是给开发看的（Keep a Changelog 格式、英文小标题、
带 commit 短 sha），而版本更新弹窗是给社员看的。让浏览器解析 Markdown 既多余又脆弱
——构建时转一次，前端只读结构化数据。

由 ``.github/workflows/image.yml`` 在 docker build 前调用，产物 ``changelog.json``
不进仓库（和 ``build_info.json`` 一样，只存在于构建上下文里）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.changelog_parse import parse_entry  # noqa: E402


def read_version(pyproject: Path) -> str:
    for line in pyproject.read_text(encoding="utf-8").split("\n"):
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            return m.group(1)
    raise SystemExit(f"{pyproject} 里读不到 version")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None, help="默认取 pyproject.toml 的 version")
    ap.add_argument("--output", default="changelog.json")
    args = ap.parse_args()

    version = args.version or read_version(ROOT / "pyproject.toml")
    changelog_path = ROOT / "CHANGELOG.md"
    if not changelog_path.is_file():
        Path(args.output).write_text("null\n", encoding="utf-8")
        print(f"gen-changelog: 没有 CHANGELOG.md，写 null 到 {args.output}", file=sys.stderr)
        return 0

    entry = parse_entry(changelog_path.read_text(encoding="utf-8"), version)
    Path(args.output).write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")

    if entry is None:
        print(f"gen-changelog: CHANGELOG.md 里没有 {version} 这一节，写 null", file=sys.stderr)
    else:
        total = sum(len(s["items"]) for s in entry["sections"])
        print(f"gen-changelog: {version} · {len(entry['sections'])} 节 / {total} 条 → {args.output}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
