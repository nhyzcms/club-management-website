#!/usr/bin/env python3
"""update_milestones.py — 发布后维护 Milestone。

    python3 scripts/update_milestones.py 1.2.0

做两件事：
1. 关掉标题为 v<本版本> 的 milestone（若开着）；
2. 开出下一个 MINOR 版本 v<major>.<minor+1>.0 的 milestone（若不存在）。

为什么只开 MINOR：patch 版本不改变规划范围，为每个 patch 单开一个 milestone
只会让看板碎掉。PATCH 的修复挂在当前 MINOR 的 milestone 下即可。

依赖 gh CLI 已认证（CI 里用 GITHUB_TOKEN）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.environ.get("RELEASE_REPO", "nhyzcms/club-management-website")


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def gh_json(*args: str) -> list[dict]:
    out = gh(*args)
    return json.loads(out) if out.strip() else []


def milestones() -> list[dict]:
    return gh_json("api", f"repos/{REPO}/milestones?state=all&per_page=100")


def close(title: str) -> bool:
    for m in milestones():
        if m["title"] == title and m["state"] == "open":
            gh(
                "api", "-X", "PATCH",
                f"repos/{REPO}/milestones/{m['number']}",
                "-f", "state=closed",
            )
            print(f"closed milestone {title} (#{m['number']})")
            return True
    print(f"milestone {title} 不存在或已关闭，跳过")
    return False


def ensure(title: str, description: str) -> bool:
    for m in milestones():
        if m["title"] == title:
            print(f"milestone {title} 已存在（{m['state']}），不重复创建")
            return False
    gh(
        "api", "-X", "POST", f"repos/{REPO}/milestones",
        "-f", f"title={title}",
        "-f", "state=open",
        "-f", f"description={description}",
    )
    print(f"created milestone {title}")
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：update_milestones.py <X.Y.Z>", file=sys.stderr)
        return 2

    version = sys.argv[1].lstrip("v")
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        print(f"版本号不是 X.Y.Z：{version}", file=sys.stderr)
        return 2

    major, minor, _patch = (int(p) for p in parts)

    close(f"v{version}")
    ensure(
        f"v{major}.{minor + 1}.0",
        f"下一个 MINOR 版本的规划里程碑（发布 v{major}.{minor + 1}.0 时自动关闭）。",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
