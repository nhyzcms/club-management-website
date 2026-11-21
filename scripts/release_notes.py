#!/usr/bin/env python3
"""release_notes.py — 从 git 历史生成分类变更记录。

用法：
    python3 scripts/release_notes.py --since v1.0.0 --until HEAD
    python3 scripts/release_notes.py --since v1.0.0 --until HEAD --format changelog-entry

输出按 SemVer 语义分类（feat / fix / perf / refactor / docs / test / ci / chore），
BREAKING 单独提到最前面——因为它的存在直接决定版本号该递增哪一位。

刻意读 commit message 的首行前缀，而不是 PR 标签：
本仓库大量改动是直推 main 的，PR 标签覆盖不全；commit 前缀才是全量的。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import OrderedDict

# 类型 → 中文小节名。顺序即输出顺序。
SECTIONS = OrderedDict(
    [
        ("breaking", "Breaking（不兼容变更）"),
        ("feat", "Added"),
        ("fix", "Fixed"),
        ("perf", "Performance"),
        ("refactor", "Changed"),
        ("docs", "Docs"),
        ("test", "Tests"),
        ("ci", "CI"),
        ("chore", "Chore"),
        ("other", "Other"),
    ]
)

# "feat(scope): 摘要" / "fix!: 摘要" / "feat(scope)!: 摘要"
#: ``changelog-entry`` 的读者是社员，不是维护者。
#: CI 怎么排队、测试怎么跑，社员不关心，而 git log 里一条不少——所以这份不写。
PUBLIC_SKIP = {"ci", "test", "chore", "build"}

SUBJECT_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<summary>.+)$")
BREAKING_FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE:\s*(.+)$", re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def latest_tag(pattern: str) -> str | None:
    """按语义版本排序取最大的 tag（git 默认排序是字典序，会把 v1.10 排在 v1.9 前面）。"""
    out = git("tag", "--list", pattern).split()
    if not out:
        return None
    return max(out, key=version_key)


def version_key(tag: str) -> tuple:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(?P<pre>[0-9A-Za-z.-]+))?$", tag.strip())
    if not m:
        return (0, 0, 0, 0, tag)
    major, minor, patch, pre = int(m[1]), int(m[2]), int(m[3]), m["pre"]
    # 有预发布标记的版本小于同号正式版
    return (major, minor, patch, 0 if pre else 1, pre or "")


def collect(since: str | None, until: str) -> list[dict]:
    rev = f"{since}..{until}" if since else until
    # %x00 分隔字段，%x1e 分隔提交，避免 message 里的换行把解析打乱
    raw = git("log", "--no-merges", f"--format=%H%x00%s%x00%b%x1e", rev)

    commits = []
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split("\x00")
        if len(parts) < 3:
            continue
        sha, subject, body = parts[0], parts[1], "\x00".join(parts[2:])

        m = SUBJECT_RE.match(subject.strip())
        ctype = (m["type"].lower() if m else "other")
        if ctype not in SECTIONS:
            ctype = "other"
        summary = m["summary"] if m else subject.strip()

        breaking = bool(m and m["bang"]) or bool(BREAKING_FOOTER_RE.search(body))
        if breaking:
            ctype = "breaking"

        commits.append(
            {"sha": sha[:7], "type": ctype, "scope": (m["scope"] if m else None), "summary": summary}
        )
    return commits


def render(commits: list[dict], *, version: str | None, fmt: str) -> str:
    buckets: dict[str, list[dict]] = {k: [] for k in SECTIONS}
    for c in commits:
        buckets[c["type"]].append(c)

    lines: list[str] = []
    if fmt == "changelog-entry":
        lines.append(f"## [{version}] - {git('log', '-1', '--format=%cs').strip()}")
        lines.append("")
    else:
        lines.append(f"共 {len(commits)} 条变更。")
        lines.append("")

    public = fmt == "changelog-entry"
    for key, title in SECTIONS.items():
        items = buckets.get(key) or []
        if public:
            items = [c for c in items if c["type"] not in PUBLIC_SKIP]
        if not items:
            continue
        lines.append(f"### {title}")
        lines.append("")
        for c in items:
            scope = f"**{c['scope']}**: " if c["scope"] else ""
            lines.append(f"- {scope}{c['summary']} ({c['sha']})")
        lines.append("")

    if not any(buckets.values()) or (public and not any(
            items for key, items in buckets.items() if key not in PUBLIC_SKIP)):
        lines.append("_本次没有记录到变更。_")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="起始 ref（不含）；省略则取最近一个 v* tag")
    ap.add_argument("--until", default="HEAD")
    ap.add_argument("--version", default=None, help="写入 changelog 条目的版本号，如 1.1.0")
    ap.add_argument("--format", choices=["release", "changelog-entry"], default="release")
    ap.add_argument("--breaking-only-check", action="store_true",
                    help="只判断有无 BREAKING，有则退出码 2（给发布流程校验版本位用）")
    args = ap.parse_args()

    since = args.since
    if since is None:
        since = latest_tag("v[0-9]*")

    commits = collect(since, args.until)

    if args.breaking_only_check:
        has = any(c["type"] == "breaking" for c in commits)
        print("breaking" if has else "no-breaking")
        return 2 if has else 0

    print(render(commits, version=args.version, fmt=args.format), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
