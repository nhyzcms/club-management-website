import { useCallback, useEffect, useState } from "react";
import type { ChangelogEntry } from "../api/version";
import ChangelogModal from "./ChangelogModal";
import { loadBuildInfo, loadChangelog } from "../hooks/useBuildInfo";

/** 上次看到的版本号存在这里。清缓存不会让弹窗重来（localStorage 是持久的）。 */
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
 * 三条规则，缺一条都会让这个功能变成骚扰：
 *   1. 只在**发布版本**上弹。开发版一天变好几次，那不是「更新」，那是我们自己在改。
 *   2. 只在**见过旧版本**时弹。首次访问的人没有「更新」可言，记下当前版本就好。
 *   3. 只在**确实有说明**时弹。CHANGELOG 里没写这一节，就别弹一个空窗。
 */
export default function ChangelogHost() {
  const [entry, setEntry] = useState<ChangelogEntry | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([loadBuildInfo(), loadChangelog()]).then(([info, log]) => {
      if (!alive) return;
      setEntry(log);

      if (!info || info.channel !== "release") return;

      const seen = readSeen();
      if (seen === null) {
        // 第一次来：把当前版本记下，不弹。下一次发版才是真正的「更新」。
        // 记版本不受「这一版有没有写说明」影响——否则这一版没写说明，
        // 等以后补上时，同一版又会对着老用户弹一次。
        writeSeen(info.version);
        return;
      }
      // 没写说明就不弹空窗。update 按钮那边也会因此不出现。
      if (seen !== info.version && log?.sections?.length) setOpen(true);
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
    loadBuildInfo().then((info) => {
      if (info?.channel === "release") writeSeen(info.version);
    });
  }, []);

  if (!open || !entry || !entry.sections.length) return null;
  return <ChangelogModal entry={entry} onClose={close} />;
}
