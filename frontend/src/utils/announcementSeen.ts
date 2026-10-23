/**
 * 本机「已看过的全站公告 id」。
 *
 * 服务端的已读台账只对登录用户有意义；但**未登录访客**（受众=全站）也会看到弹窗，
 * 没有行可写，只能记在浏览器本地，否则每刷新一次就再弹一次。
 *
 * 登录用户也记一份：`POST /read/` 是异步的，本地先记住可以避免「关掉弹窗后立刻刷新
 * 又弹出来」的窗口期。跨设备一致性由服务端台账保证。
 */
const KEY = "cobalt:announcement-seen";
const MAX_IDS = 100;

function readAll(): number[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  } catch {
    return [];
  }
}

export function seenAnnouncementIds(): number[] {
  return readAll();
}

export function rememberAnnouncementSeen(id: number): void {
  try {
    const ids = readAll().filter((v) => v !== id);
    ids.push(id);
    window.localStorage.setItem(KEY, JSON.stringify(ids.slice(-MAX_IDS)));
  } catch {
    /* 隐私模式下 localStorage 可能不可写：退化为「本次会话内记住」即可 */
  }
}

export function isAnnouncementSeen(id: number): boolean {
  return readAll().includes(id);
}

export function filterUnseenAnnouncements<T extends { id: number }>(rows: T[]): T[] {
  const seen = new Set(readAll());
  return rows.filter((row) => !seen.has(row.id));
}

export const ANNOUNCEMENT_SEEN_KEY = KEY;
