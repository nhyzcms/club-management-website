/**
 * 考试看板推送：访客可连 `/ws/exam-board/`，只收不发。
 * HTTP 仍是事实源；socket 提示刷新课表 / 展示题目误刊。断线指数退避重连。
 */

export type ExamBoardPushKind = "exam" | "errata" | "errata_cleared";

export interface ExamBoardPushEvent {
  event: ExamBoardPushKind;
  payload: Record<string, unknown>;
}

type Unsub = () => void;

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

let wanted = false;
let socket: WebSocket | null = null;
let backoff = MIN_BACKOFF_MS;
let reconnectTimer: number | null = null;

export type ExamBoardSocketState = "idle" | "connecting" | "open" | "closed";

const eventListeners = new Set<(ev: ExamBoardPushEvent) => void>();
const statusListeners = new Set<(state: ExamBoardSocketState) => void>();

let socketState: ExamBoardSocketState = "idle";

function setSocketState(next: ExamBoardSocketState) {
  if (socketState === next) return;
  socketState = next;
  statusListeners.forEach((fn) => fn(socketState));
}

export function getExamBoardSocketState(): ExamBoardSocketState {
  return socketState;
}

export function onExamBoardSocketStatus(fn: (state: ExamBoardSocketState) => void): Unsub {
  statusListeners.add(fn);
  fn(socketState);
  return () => { statusListeners.delete(fn); };
}

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/exam-board/`;
}

function parseEvent(raw: string): ExamBoardPushEvent | null {
  try {
    const data = JSON.parse(raw);
    const event = data?.event;
    if (event !== "exam" && event !== "errata" && event !== "errata_cleared") return null;
    const payload = data?.payload && typeof data.payload === "object" && !Array.isArray(data.payload)
      ? data.payload
      : {};
    return { event, payload };
  } catch {
    return null;
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
  setSocketState("connecting");
  let next: WebSocket;
  try {
    next = new WebSocket(wsUrl());
  } catch {
    setSocketState("closed");
    scheduleReconnect();
    return;
  }
  socket = next;
  next.onopen = () => {
    if (socket !== next) return;
    backoff = MIN_BACKOFF_MS;
    setSocketState("open");
  };
  next.onmessage = (ev) => {
    const parsed = parseEvent(typeof ev.data === "string" ? ev.data : "");
    if (!parsed) return;
    eventListeners.forEach((fn) => fn(parsed));
  };
  next.onclose = () => {
    if (socket === next) socket = null;
    if (wanted) {
      setSocketState("connecting");
      scheduleReconnect();
    } else {
      setSocketState("closed");
    }
  };
  next.onerror = () => {
    try { next.close(); } catch { /* ignore */ }
  };
}

export function startExamBoardSocket() {
  wanted = true;
  connect();
}

export function stopExamBoardSocket() {
  wanted = false;
  if (reconnectTimer != null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
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
  setSocketState("closed");
}

export function onExamBoardEvent(fn: (ev: ExamBoardPushEvent) => void): Unsub {
  eventListeners.add(fn);
  return () => { eventListeners.delete(fn); };
}
