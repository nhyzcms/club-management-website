/**
 * 手机版（/m）的未读角标：私信 + 通知（2026-10-17）。
 *
 * 为什么单独做一个模块级 store，而不是每个页面各写一个 useEffect：
 *  - /m 的每个页面底部都有 MobileTabBar，首页还要额外显示「消息」入口的红点，
 *    各写一份就会在同一屏打出 2~3 份重复请求（服务器只有 2 核 2 GB，别浪费）；
 *  - 这里做「一份状态 + 多份订阅 + 单一计时器」，最后一个订阅者卸载时停表。
 *
 * 数据源与桌面 AppShell 完全一致（HTTP 是事实源，ADR-0015）：
 *  - 网页版浏览器：30 s 轮询 + 窗口可见/获得焦点时立即刷新；
 *  - App 壳内：除轮询外，原生层收到新私信/通知时会向页面派发常量事件 `club:unread`
 *    （见 app 仓库 MainActivity.bindPushBridge），这里监听它即时刷新，红点几乎无延迟。
 *
 * 刻意**不**在手机版里再起一条 WebSocket：
 *  - App 壳已经有一条原生 WS（常驻前台服务保活），网页再连一条纯属浪费；
 *  - 浏览器侧 30 s 一次的两个轻量计数请求足够，且避免与桌面 AppShell 的单例 socket
 *    互相 stop（两者可能短暂同时挂载）。
 */

import { useEffect, useState } from "react";
import { api } from "./client";
import { messagingApi } from "./messaging";
import { getSitePolicy } from "./sitePolicy";

export interface UnreadCounts {
  /** 未读私信条数（/messaging/conversations/unread_count/）。 */
  dm: number;
  /** 未读通知条数（/messaging/notifications/unread_count/）。 */
  notif: number;
  /** 当前是否已登录（未登录时入口不显示红点）。 */
  signedIn: boolean;
  /** 是否至少成功拉取过一次（避免首屏把"还没数据"当成"没有未读"）。 */
  ready: boolean;
}

const POLL_MS = 30_000;
const MIN_GAP_MS = 2_000;

const EMPTY: UnreadCounts = { dm: 0, notif: 0, signedIn: false, ready: false };

let snapshot: UnreadCounts = EMPTY;
const listeners = new Set<() => void>();
let consumers = 0;
let timer: number | null = null;
let inflight = false;
let lastFetchAt = 0;

function publish(next: UnreadCounts) {
  if (
    next.dm === snapshot.dm
    && next.notif === snapshot.notif
    && next.signedIn === snapshot.signedIn
    && next.ready === snapshot.ready
  ) {
    return;
  }
  snapshot = next;
  listeners.forEach((fn) => fn());
}

export function getUnreadCounts(): UnreadCounts {
  return snapshot;
}

/** 红点/角标统一格式：超过 99 显示 99+（与桌面顶栏一致）。 */
export function formatUnreadCount(n: number): string {
  return n > 99 ? "99+" : String(n);
}

async function refresh(): Promise<void> {
  if (inflight) return;
  inflight = true;
  lastFetchAt = Date.now();
  try {
    const me: any = await api.me().catch(() => null);
    if (!me?.user) {
      publish({ dm: 0, notif: 0, signedIn: false, ready: true });
      return;
    }
    const verified = !!me?.profile?.is_verified;
    const dmEnabled = verified && getSitePolicy().dms_enabled;
    const [dm, notif] = await Promise.all([
      dmEnabled
        ? messagingApi.unreadCount().catch(() => ({ total: 0 }))
        : Promise.resolve({ total: 0 }),
      messagingApi.notificationUnreadCount().catch(() => ({ total: 0 })),
    ]);
    publish({
      dm: Number(dm?.total) || 0,
      notif: Number(notif?.total) || 0,
      signedIn: true,
      ready: true,
    });
  } finally {
    inflight = false;
  }
}

function onVisible() {
  if (document.visibilityState === "visible") void refresh();
}

function onFocus() {
  void refresh();
}

/** App 壳派发的常量事件（不带任何数据，只表示"未读可能变了"）。 */
function onAppUnread() {
  void refresh();
}

function start() {
  if (timer == null) {
    timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
  }
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("focus", onFocus);
  window.addEventListener("club:unread", onAppUnread);
  if (Date.now() - lastFetchAt > MIN_GAP_MS) void refresh();
}

function stop() {
  if (timer != null) {
    window.clearInterval(timer);
    timer = null;
  }
  document.removeEventListener("visibilitychange", onVisible);
  window.removeEventListener("focus", onFocus);
  window.removeEventListener("club:unread", onAppUnread);
}

export function subscribeUnreadCounts(fn: () => void): () => void {
  listeners.add(fn);
  consumers += 1;
  if (consumers === 1) start();
  return () => {
    listeners.delete(fn);
    consumers = Math.max(0, consumers - 1);
    if (consumers === 0) stop();
  };
}

/** 订阅未读角标（首个订阅者挂载时自动开始，最后一个卸载时自动停表）。 */
export function useUnreadCounts(): UnreadCounts {
  const [counts, setCounts] = useState(snapshot);
  useEffect(() => subscribeUnreadCounts(() => setCounts(snapshot)), []);
  return counts;
}
