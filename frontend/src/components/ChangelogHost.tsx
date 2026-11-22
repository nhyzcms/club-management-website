import { useCallback, useEffect, useState } from "react";
import type { ChangelogEntry } from "../api/version";
import ChangelogModal from "./ChangelogModal";
import { loadChangelog } from "../hooks/useBuildInfo";

/** 上次看过的**发行说明版本**存在这里（不是构建版本号）。
 *  清缓存不会让弹窗重来（localStorage 是持久的）。 */
export const SEEN_VERSION_KEY = "club.seenVersion";

/** 页脚「更新日志」用事件打开，省得把弹窗状态提到 AppShell。 */
export const OPEN_CHANGELOG_EVENT = "club:open-changelog";

export function openChangelog() {
  window.dispatchEvent(new Event(OPEN_CHANGELOG_EVENT));
}

function readSeen(): string | null {
  try {
    return window.localStorage.getItem(SEEN_VERSION_KEY);
  } catch {
    return null; // 隐私模式 / 禁用存储：当作没见过，但也不打扰
  }
}

function writeSeen(version: string) {
  try {
    window.localStorage.setItem(SEEN_VERSION_KEY, version);
  } catch {
    /* 存不了就算了，下次可能再弹一次，比报错好 */
  }
}

/**
 * 版本更新提示。
 *
 * 触发条件：**发行说明的版本变了，而且这个人见过上一版**。
 *
 * 为什么不再按 channel 判（曾经要求 channel === "release"）：
 * 构建脚本只有在「构建 ref 正好是 tag」或「这个提交自己改了 pyproject 版本」
 * 时才把 channel 标成 release。而 main 在发布之后还要进 hotfix、回流，
 * 生产实际跑的永远是 tag 之后的 dev 构建——那条规则让弹窗在线上从不出现，
 * 功能等于没做。
 *
 * changelog.json 只在发版时变（它由 CHANGELOG.md 生成，开发分支不动这个文件），
 * 所以按「发行说明版本」判，更贴近这里真正想表达的东西：
 * 不是「这是个 tag 构建」，而是「这一版改了什么，你看过没有」。
 *
 * 另外两条保留：首次访问只记录不弹；没有正文不弹空窗。
 */
export default function ChangelogHost() {
  const [entry, setEntry] = useState<ChangelogEntry | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    loadChangelog().then((log) => {
      if (!alive) return;
      setEntry(log);

      const version = log?.version;
      if (!version) return; // 没有发行说明，就没有「更新」可讲

      const seen = readSeen();
      if (seen === null) {
        // 第一次来：把当前版本记下，不弹。下一次发版才是真正的「更新」。
        // 记版本不受「这一版有没有写说明」影响——否则这一版没写说明，
        // 等以后补上时，同一版又会对着老用户弹一次。
        writeSeen(version);
        return;
      }
      // 没写说明就不弹空窗。「更新日志」按钮那边也会因此不出现。
      if (seen !== version && log.sections.length) setOpen(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener(OPEN_CHANGELOG_EVENT, handler);
    return () => window.removeEventListener(OPEN_CHANGELOG_EVENT, handler);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    if (entry?.version) writeSeen(entry.version);
  }, [entry]);

  if (!open || !entry || !entry.sections.length) return null;
  return <ChangelogModal entry={entry} onClose={close} />;
}
