"""CHANGELOG.md 的解析规则（纯函数，不引 Django）。

两处共用：构建时 ``scripts/gen_changelog.py`` 把它转成 ``changelog.json``；
本地开发没有构建产物时，``common.changelog`` 直接解析 Markdown 兜底。

放这里而不是各写一份：解析规则一旦分叉，线上弹窗和 CHANGELOG.md 说的就不是同一件事。
"""
from __future__ import annotations

import re

#: 英文小标题 → 社员看得懂的中文
SECTION_TITLES = {
    "Breaking": "不兼容变更",
    "Breaking（不兼容变更）": "不兼容变更",
    "Added": "新增",
    "Fixed": "修复",
    "Changed": "变更",
    "Performance": "性能",
    "Docs": "文档",
    "Tests": "测试",
    "CI": "CI",
    "Chore": "维护",
}

VERSION_RE = re.compile(r"^##\s*\[(?P<version>[^\]]+)\]\s*(?:-\s*(?P<date>.+))?$")
SECTION_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
ITEM_RE = re.compile(r"^[-*]\s+(?P<text>.+)$")
#: 版本小节开头的引用块 = 给社员看的一句话摘要。
#: 自动生成的部分是 commit 原文，只有人能把「改了什么」翻译成「和你有什么关系」。
SUMMARY_RE = re.compile(r"^>\s?(?P<text>.*)$")


def clean_item(text: str) -> str:
    """去掉 Markdown 装饰，留下人话。"""
    return text.replace("**", "").replace("`", "").strip()


def parse_entry(changelog: str, version: str) -> dict | None:
    """取出某个版本的小节。没写这一节就返回 None（不是空 dict）。"""
    lines = changelog.split("\n")
    start = None
    released = None
    for i, line in enumerate(lines):
        m = VERSION_RE.match(line.strip())
        if m and m.group("version").strip() == version:
            start = i + 1
            released = (m.group("date") or "").strip() or None
            break
    if start is None:
        return None

    sections: list[dict] = []
    summary_lines: list[str] = []
    current: dict | None = None
    for line in lines[start:]:
        stripped = line.strip()
        if VERSION_RE.match(stripped):  # 走到下一个版本小节
            break
        if current is None:
            sm_sum = SUMMARY_RE.match(stripped)
            if sm_sum:
                if sm_sum.group("text").strip():
                    summary_lines.append(clean_item(sm_sum.group("text")))
                continue
        sm = SECTION_RE.match(stripped)
        if sm:
            title = sm.group("title")
            current = {"title": SECTION_TITLES.get(title, title), "items": []}
            sections.append(current)
            continue
        im = ITEM_RE.match(stripped)
        if im and current is not None:
            current["items"].append(clean_item(im.group("text")))

    sections = [s for s in sections if s["items"]]
    summary = " ".join(summary_lines).strip() or None
    return {"version": version, "released": released, "summary": summary, "sections": sections}
