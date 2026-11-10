/**
 * 消息推送客户端：已登录用户连 `/ws/messaging/`，只收不发业务数据。
 * HTTP 仍是事实源；socket 仅提示刷新。断线指数退避重连；打开时重订当前评论区。
 * 服务端未就绪时连接失败不影响页面——评论 / 私信 / 通知仍走 HTTP。
 */

export type MessagingPushKind = "dm" | "notification" | "comment" | "unread";

export interface MessagingPushEvent {
  event: MessagingPushKind;
  payload: Record<string, unknown>;
}

type Unsub = () => void;

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

let wanted = false;
let socket: WebSocket | null = null;
let backoff = MIN_BACKOFF_MS;
let reconnectTimer: number | null = null;

const subscribedThreads = new Set<number>();
const openListeners = new Set<() => void>();
const eventListeners = new Set<(ev: MessagingPushEvent) => void>();

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/messaging/`;
}

function parseEvent(raw: string): MessagingPushEvent | null {
  try {
    const data = JSON.parse(raw);
    const event = data?.event ?? data?.type;
    if (event !== "dm" && event !== "notification" && event !== "comment" && event !== "unread") return null;
    const payload = data?.payload && typeof data.payload === "object" && !Array.isArray(data.payload)
      ? data.payload
      : data;
    return { event, payload };
  } catch {
    return null;
  }
}

function send(obj: Record<string, unknown>) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(obj));
  }
}

function scheduleReconnect() {
  if (!wanted || reconnectTimer != null) return;
  const wait = backoff;
  backoff = Math.min(MAX_BACKOFF_MS, backoff * 2);
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, wait);
}

function connect() {
  if (!wanted) return;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  let next: WebSocket;
  try {
    next = new WebSocket(wsUrl());
  } catch {
    scheduleReconnect();
    return;
  }
  socket = next;
  next.onopen = () => {
    if (socket !== next) return;
    backoff = MIN_BACKOFF_MS;
    subscribedThreads.forEach((id) => {
      send({ action: "subscribe_thread", thread_id: id });
    });
    openListeners.forEach((fn) => fn());
  };
  next.onmessage = (ev) => {
    const parsed = parseEvent(typeof ev.data === "string" ? ev.data : "");
    if (!parsed) return;
    eventListeners.forEach((fn) => fn(parsed));
  };
  next.onclose = () => {
    if (socket === next) socket = null;
    scheduleReconnect();
  };
  next.onerror = () => {
    try { next.close(); } catch { /* ignore */ }
  };
}

/** 登录后调用；幂等。 */
export function startMessagingSocket() {
  wanted = true;
  connect();
}

/** 登出后调用。 */
export function stopMessagingSocket() {
  wanted = false;
  if (reconnectTimer != null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  subscribedThreads.clear();
  const current = socket;
  socket = null;
  if (current) {
    current.onclose = null;
    current.onerror = null;
    current.onmessage = null;
    current.onopen = null;
    try { current.close(); } catch { /* ignore */ }
  }
  backoff = MIN_BACKOFF_MS;
}

export function subscribeThread(threadId: number) {
  if (!Number.isFinite(threadId)) return;
  subscribedThreads.add(threadId);
  send({ action: "subscribe_thread", thread_id: threadId });
}

export function unsubscribeThread(threadId: number) {
  subscribedThreads.delete(threadId);
  send({ action: "unsubscribe_thread", thread_id: threadId });
}

export function onMessagingOpen(fn: () => void): Unsub {
  openListeners.add(fn);
  return () => { openListeners.delete(fn); };
}

export function onMessagingEvent(fn: (ev: MessagingPushEvent) => void): Unsub {
  eventListeners.add(fn);
  return () => { eventListeners.delete(fn); };
}

/** 本地发出与 WS 同形的事件（如 mark_read 完成后刷新未读徽标）。 */
export function emitMessagingEvent(ev: MessagingPushEvent) {
  eventListeners.forEach((fn) => fn(ev));
}
