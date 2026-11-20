#!/usr/bin/env python3
"""bump_version.py — 按 SemVer 递增版本号，同步 pyproject.toml 与 CHANGELOG.md。

用法：
    python3 scripts/bump_version.py --bump minor
    python3 scripts/bump_version.py --override 2.0.0
    python3 scripts/bump_version.py --bump patch --dry-run

规则（SemVer 2.0.0）：
    major  不兼容变更      → X+1.0.0
    minor  向后兼容的新功能 → X.Y+1.0
    patch  向后兼容的修复   → X.Y.Z+1

首次发布（仓库里还没有 v* tag）一律落到 1.0.0——0.x 的语义是「公开接口随时会变」，
而本站已经有生产用户，继续挂 0.x 只会让「升级风险」失去刻度。

不提交、不推送、不打 tag：脚本只改工作区文件，发布流水线负责后续动作。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def latest_tag() -> str | None:
    tags = git("tag", "--list", "v[0-9]*").split()
    if not tags:
        return None

    def key(t: str) -> tuple:
        m = SEMVER_RE.match(t.lstrip("v"))
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)

    return max(tags, key=key)


def current_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("pyproject.toml 里没有 version 字段")
    return m.group(1)


def next_version(current: str, bump: str, override: str | None) -> str:
    if override:
        if not SEMVER_RE.match(override):
            raise SystemExit(f"--override 必须是 X.Y.Z：{override}")
        return override

    m = SEMVER_RE.match(current)
    if not m:
        raise SystemExit(f"当前版本不是 X.Y.Z，无法自动递增：{current}")
    major, minor, patch = (int(x) for x in m.groups())

    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"未知的 bump 类型：{bump}")


def write_pyproject(version: str) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    new, n = re.subn(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise SystemExit("pyproject.toml 的 version 行没替换成功")
    PYPROJECT.write_text(new, encoding="utf-8")


def notes_for(version: str, since: str | None) -> str:
    cmd = [sys.executable, str(ROOT / "scripts" / "release_notes.py"), "--until", "HEAD", "--version", version, "--format", "changelog-entry"]
    if since:
        cmd += ["--since", since]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def write_changelog(version: str, entry: str) -> None:
    today = dt.date.today().isoformat()
    unreleased = "## [Unreleased]\n\n_（下个版本待归类；发版时整段移到版本小节下。）_\n"

    if CHANGELOG.exists():
        text = CHANGELOG.read_text(encoding="utf-8")
    else:
        text = "# Changelog\n\n格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，\n版本号遵循 [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/)。\n\n"

    # 去掉旧的 Unreleased 段（它到下一个 "## [" 之前）
    text = re.sub(r"## \[Unreleased\][\s\S]*?(?=\n## \[|\Z)", "", text).rstrip() + "\n\n"

    # release_notes.py --format changelog-entry 已经输出了 "## [X.Y.Z] - 日期" 的标题，
    # 这里不能再替换一次（否则标题会重复成 "## [1.0.0] - 2026-11-201.0.0] - ..."）

    if "# Changelog" in text:
        head, _, rest = text.partition("\n\n")
        body = rest.lstrip("\n")
    else:
        head, body = "# Changelog\n\n", text

    CHANGELOG.write_text(f"{head}\n\n{unreleased}\n{entry.strip()}\n\n{body}".rstrip() + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bump", choices=["major", "minor", "patch"], default="patch")
    ap.add_argument("--override", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cur = current_version()
    tag = latest_tag()

    # 还没有任何 v* tag → 首次发布固定 1.0.0
    if tag is None and args.override is None:
        new = "1.0.0"
    else:
        new = next_version(cur, args.bump, args.override)

    print(f"current={cur} latest_tag={tag or '(none)'} next={new}")

    if args.dry_run:
        return 0

    write_pyproject(new)
    entry = notes_for(new, tag)
    write_changelog(new, entry)
    print(f"wrote pyproject.toml -> {new}")
    print(f"wrote CHANGELOG.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
