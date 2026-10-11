import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import {
  examApi,
  type Exam,
  type ExamBatch,
  type ExamErrata,
  type ExamListItem,
  type ExamSubject,
  type ExamWritePayload,
} from "../api/exam";
import { onExamBoardEvent, onExamBoardSocketStatus, startExamBoardSocket, stopExamBoardSocket, type ExamBoardSocketState } from "../api/examSocket";
import { playExamCue, speakExamVoice, unlockExamBoardAudio } from "../examBoard/audio";
import {
  applyExamBoardMascotClass,
  loadExamBoardPrefs,
  saveExamBoardPrefs,
  type ExamBoardPrefs,
} from "../examBoard/prefs";
import {
  subjectRowInvalid,
  validateExamDraft,
  type DraftBatch,
} from "../examBoard/validate";
import { useLoginModal } from "../components/LoginModalProvider";
import { speakMascot } from "../components/mascot/speak";
import "../styles/exam-board.css";

const SYNC_INTERVAL = 5 * 60 * 1000;
const WARN_SECONDS = 15 * 60;
const FADE_MS = 280;
const POPUP_MS = 2800;
const RECYCLE_GAP_MS = 750;
const ZOOM_CYCLE_MS = 60 * 1000;
const SCHEDULE_COLLAPSE_MS = 5 * 60 * 1000;
const POPUP_SEEN_KEY = "examBoardErrataPopup";
const SELECTION_KEY = "examBoardSelection";
const GUIDE_KEY = "examBoardInvigilatorGuide";
const SHANGHAI = "Asia/Shanghai";

type BoardStatus =
  | { kind: "empty" }
  | { kind: "idle" }
  | { kind: "active"; subject: string; start: string; end: string; remainSec: number }
  | { kind: "rest"; nextSubject: string; nextStart: string; untilSec: number }
  | { kind: "done" };

type Cue =
  | { kind: "ending"; subject: string; remainSec: number }
  | { kind: "approaching"; subject: string; start: string; untilSec: number };

type DisplayFields = {
  title: string;
  batchName: string;
  subject: string;
  startCaption: string;
  start: string;
  end: string;
  restHint: string;
};

function shanghaiParts(ms: number) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: SHANGHAI,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(ms));
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? "00";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    time: `${get("hour")}:${get("minute")}:${get("second")}`,
    hm: `${get("hour")}:${get("minute")}`,
  };
}

function hm(value: string) {
  return (value || "").slice(0, 5);
}

function toSeconds(value: string) {
  const parts = (value || "00:00:00").split(":");
  const h = Number(parts[0]) || 0;
  const m = Number(parts[1]) || 0;
  const s = Number(parts[2]) || 0;
  return h * 3600 + m * 60 + s;
}

function formatRemain(sec: number) {
  if (sec <= 60) return "不到 1 分钟";
  return `${Math.ceil(sec / 60)} 分钟`;
}

function formatSyncTime(ms: number | null) {
  if (ms == null) return "尚未同步";
  return shanghaiParts(ms).time;
}

function socketStateLabel(state: ExamBoardSocketState) {
  if (state === "open") return "已连接";
  if (state === "connecting") return "连接中";
  if (state === "closed") return "已断开";
  return "未连接";
}

function newKey() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadSelection(): { examId: number | null; batchId: number | null } {
  try {
    const raw = localStorage.getItem(SELECTION_KEY);
    if (!raw) return { examId: null, batchId: null };
    const parsed = JSON.parse(raw);
    return {
      examId: typeof parsed.examId === "number" ? parsed.examId : null,
      batchId: typeof parsed.batchId === "number" ? parsed.batchId : null,
    };
  } catch {
    return { examId: null, batchId: null };
  }
}

function examToDraft(exam: Exam): { title: string; batches: DraftBatch[] } {
  return {
    title: exam.title,
    batches: exam.batches.map((b) => ({
      key: `b-${b.id}`,
      name: b.name,
      subjects: b.subjects.map((s) => ({
        key: `s-${s.id}`,
        name: s.name,
        exam_date: s.exam_date,
        start_time: hm(s.start_time),
        end_time: hm(s.end_time),
      })),
    })),
  };
}

function emptyDraft() {
  return {
    title: "",
    batches: [
      {
        key: newKey(),
        name: "高一",
        subjects: [
          { key: newKey(), name: "语文", exam_date: "", start_time: "09:00", end_time: "11:30" },
        ],
      },
    ],
  };
}

function draftToPayload(title: string, batches: DraftBatch[]): ExamWritePayload {
  return {
    title: title.trim(),
    batches: batches.map((b, i) => ({
      name: b.name.trim(),
      sort_order: i,
      subjects: b.subjects
        .filter((s) => s.name.trim() && s.exam_date && s.start_time && s.end_time)
        .map((s, j) => ({
          name: s.name.trim(),
          exam_date: s.exam_date,
          start_time: s.start_time,
          end_time: s.end_time,
          sort_order: j,
        })),
    })),
  };
}

function matchBoard(subjects: ExamBatch["subjects"], nowMs: number): BoardStatus {
  if (!subjects.length) return { kind: "empty" };
  const { date, time, hm: nowHm } = shanghaiParts(nowMs);
  const nowSec = toSeconds(time);
  const today = subjects
    .filter((s) => s.exam_date === date)
    .slice()
    .sort((a, b) => hm(a.start_time).localeCompare(hm(b.start_time)));
  if (!today.length) return { kind: "idle" };
  for (const s of today) {
    const start = hm(s.start_time);
    const end = hm(s.end_time);
    if (nowHm >= start && nowHm < end) {
      return {
        kind: "active",
        subject: s.name,
        start,
        end,
        remainSec: Math.max(0, toSeconds(end) - nowSec),
      };
    }
  }
  const next = today.find((s) => hm(s.start_time) > nowHm);
  if (next) {
    const nextStart = hm(next.start_time);
    return {
      kind: "rest",
      nextSubject: next.name,
      nextStart,
      untilSec: Math.max(0, toSeconds(nextStart) - nowSec),
    };
  }
  return { kind: "done" };
}

function fieldsFromStatus(status: BoardStatus, title = "暂无考试", batchName = ""): DisplayFields {
  const base = { title, batchName };
  if (status.kind === "active") {
    return {
      ...base,
      subject: status.subject,
      startCaption: "开始时间：",
      start: status.start,
      end: status.end,
      restHint: "",
    };
  }
  if (status.kind === "rest") {
    return {
      ...base,
      subject: "休息",
      startCaption: "下场开始：",
      start: status.nextStart,
      end: "--:--",
      restHint: `下场：${status.nextSubject}`,
    };
  }
  return {
    ...base,
    subject: status.kind === "done" ? "已结束" : "无",
    startCaption: "开始时间：",
    start: "--:--",
    end: "--:--",
    restHint: "",
  };
}

function fieldKey(fields: DisplayFields) {
  return `${fields.title}|${fields.batchName}|${fields.subject}|${fields.startCaption}|${fields.start}|${fields.end}|${fields.restHint}`;
}

function subjectPhase(subject: ExamSubject, nowMs: number): "done" | "active" | "upcoming" {
  const { date, hm: nowHm } = shanghaiParts(nowMs);
  const start = hm(subject.start_time);
  const end = hm(subject.end_time);
  if (subject.exam_date < date || (subject.exam_date === date && nowHm >= end)) return "done";
  if (subject.exam_date === date && nowHm >= start && nowHm < end) return "active";
  return "upcoming";
}

function phaseLabel(phase: "done" | "active" | "upcoming") {
  if (phase === "done") return "已结束";
  if (phase === "active") return "进行中";
  return "未开始";
}

function cueFromStatus(status: BoardStatus): Cue | null {
  if (status.kind === "active" && status.remainSec > 0 && status.remainSec <= WARN_SECONDS) {
    return { kind: "ending", subject: status.subject, remainSec: status.remainSec };
  }
  if (status.kind === "rest" && status.untilSec > 0 && status.untilSec <= WARN_SECONDS) {
    return {
      kind: "approaching",
      subject: status.nextSubject,
      start: status.nextStart,
      untilSec: status.untilSec,
    };
  }
  return null;
}

function errataStillLive(item: ExamErrata, nowMs: number): boolean {
  if (!item.expires_at) return true;
  const exp = Date.parse(item.expires_at);
  return Number.isNaN(exp) || exp > nowMs;
}

function pickLine(lines: string[]) {
  return lines[Math.floor(Math.random() * lines.length)];
}

function readPopupSeen(): Set<number> {
  try {
    const raw = sessionStorage.getItem(POPUP_SEEN_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.filter((n) => typeof n === "number") : []);
  } catch {
    return new Set();
  }
}

function writePopupSeen(ids: Set<number>) {
  try {
    sessionStorage.setItem(POPUP_SEEN_KEY, JSON.stringify([...ids]));
  } catch {
    /* ignore */
  }
}

function guideDismissed(): boolean {
  try {
    return localStorage.getItem(GUIDE_KEY) === "1";
  } catch {
    return false;
  }
}

function dismissGuide() {
  try {
    localStorage.setItem(GUIDE_KEY, "1");
  } catch {
    /* ignore */
  }
}

function isPageFullscreen(): boolean {
  return document.fullscreenElement != null;
}

async function togglePageFullscreen() {
  if (isPageFullscreen()) {
    await document.exitFullscreen();
    return;
  }
  await document.documentElement.requestFullscreen();
}

function ErrataCard({
  errata,
  compact = false,
  isNew = false,
  isZoomed = false,
  asButton = true,
  onOpen,
}: {
  errata: ExamErrata;
  compact?: boolean;
  isNew?: boolean;
  isZoomed?: boolean;
  asButton?: boolean;
  onOpen?: (item: ExamErrata) => void;
}) {
  const className = `errata-card${compact ? " compact" : ""}${isNew ? " is-new" : ""}${isZoomed ? " is-zoomed" : ""}`;
  const body = (
    <>
      {!compact && <div className="errata-kicker">题目误刊</div>}
      {errata.image_url && <img src={errata.image_url} alt="" width={800} height={500} />}
      {errata.text && <p>{errata.text}</p>}
      {asButton && <span className="errata-zoom-hint">{compact ? "放大" : "点击空白处关闭"}</span>}
    </>
  );
  if (!asButton) return <div className={className}>{body}</div>;
  return (
    <button
      type="button"
      className={className}
      onClick={() => onOpen?.(errata)}
      title={compact ? "放大查看这张题目误刊" : undefined}
    >
      {body}
    </button>
  );
}

function ScheduleRail({
  batch,
  nowMs,
}: {
  batch: ExamBatch | null;
  nowMs: number;
}) {
  const [open, setOpen] = useState(false);
  const hoverRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const rows = (batch?.subjects ?? [])
    .slice()
    .sort((a, b) => `${a.exam_date} ${hm(a.start_time)}`.localeCompare(`${b.exam_date} ${hm(b.start_time)}`));
  let lastDate = "";

  const armCollapse = () => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      if (!hoverRef.current) setOpen(false);
    }, SCHEDULE_COLLAPSE_MS);
  };

  useEffect(() => () => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
  }, []);

  return (
    <aside
      className={`schedule-rail${open ? " is-open" : " is-collapsed"}`}
      aria-label="考试时间表"
      onMouseEnter={() => {
        hoverRef.current = true;
        if (timerRef.current != null) {
          window.clearTimeout(timerRef.current);
          timerRef.current = null;
        }
      }}
      onMouseLeave={() => {
        hoverRef.current = false;
        if (open) armCollapse();
      }}
    >
      <button
        type="button"
        className="schedule-rail-head"
        onClick={() => {
          setOpen((current) => {
            const next = !current;
            if (next) armCollapse();
            return next;
          });
        }}
        title={open ? "收起时间表" : "展开时间表"}
      >
        <span>时间表</span>
        {batch && <span className="schedule-rail-batch">{batch.name}</span>}
        <span className="schedule-rail-toggle">{open ? "收起" : "展开"}</span>
      </button>
      {open && rows.length === 0 && <p className="schedule-empty">该批次暂无科目</p>}
      {open && (
        <ol className="schedule-list">
          {rows.map((subject) => {
            const phase = subjectPhase(subject, nowMs);
            const showDate = subject.exam_date !== lastDate;
            lastDate = subject.exam_date;
            return (
              <li key={subject.id} className={`schedule-row is-${phase}`}>
                {showDate && <div className="schedule-date">{subject.exam_date}</div>}
                <div className="schedule-row-body">
                  <span className={`schedule-phase is-${phase}`}>{phaseLabel(phase)}</span>
                  <span className="schedule-name">{subject.name}</span>
                  <span className="schedule-time">{hm(subject.start_time)}–{hm(subject.end_time)}</span>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}

export default function ExamBoardPage() {
  const { openLogin, authNonce } = useLoginModal();
  const [canManage, setCanManage] = useState(false);
  const [exams, setExams] = useState<ExamListItem[]>([]);
  const [exam, setExam] = useState<Exam | null>(null);
  const [batchId, setBatchId] = useState<number | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [tab, setTab] = useState<"display" | "edit" | "errata">("display");
  const [currentTime, setCurrentTime] = useState("00:00:00");
  const [status, setStatus] = useState<BoardStatus>({ kind: "idle" });
  const [errataList, setErrataList] = useState<ExamErrata[]>([]);
  const [popupId, setPopupId] = useState<number | null>(null);
  const [zoomed, setZoomed] = useState<ExamErrata | null>(null);
  const [prefs, setPrefs] = useState<ExamBoardPrefs>(loadExamBoardPrefs);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBatches, setDraftBatches] = useState<DraftBatch[]>(emptyDraft().batches);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [errataText, setErrataText] = useState("");
  const [errataFile, setErrataFile] = useState<File | null>(null);
  const [fields, setFields] = useState<DisplayFields>(() => fieldsFromStatus({ kind: "idle" }));
  const [fade, setFade] = useState<"in" | "out" | "">("");
  const [isFullscreen, setIsFullscreen] = useState(isPageFullscreen);
  const [showGuide, setShowGuide] = useState(() => !guideDismissed());
  const [clockSyncedAt, setClockSyncedAt] = useState<number | null>(null);
  const [clockRttMs, setClockRttMs] = useState<number | null>(null);
  const [dataSyncedAt, setDataSyncedAt] = useState<number | null>(null);
  const [socketState, setSocketState] = useState<ExamBoardSocketState>("idle");
  const timeOffsetRef = useRef(0);
  const fieldKeyRef = useRef(fieldKey(fieldsFromStatus({ kind: "idle" })));
  const fadeTimerRef = useRef<number | null>(null);
  const splashTimerRef = useRef<number | null>(null);
  const spokenRef = useRef(new Set<string>());
  const prevKindRef = useRef<BoardStatus["kind"]>("idle");
  const recyclingRef = useRef(false);
  const popupSeenRef = useRef<Set<number>>(readPopupSeen());
  const paperKindRef = useRef<BoardStatus["kind"]>("idle");
  const prevCueKindRef = useRef<Cue["kind"] | null>(null);
  const batchIdRef = useRef<number | null>(null);
  const errataListRef = useRef<ExamErrata[]>([]);
  const liveErrataRef = useRef<ExamErrata[]>([]);
  const recycledByBatchRef = useRef<Map<number, Set<number>>>(new Map());

  const batch = useMemo(
    () => exam?.batches.find((b) => b.id === batchId) ?? exam?.batches[0] ?? null,
    [exam, batchId],
  );

  const ingestErrata = useCallback((rows: ExamErrata[]) => {
    const bid = batchIdRef.current;
    const recycled = bid != null ? recycledByBatchRef.current.get(bid) : undefined;
    const ordered = rows
      .slice()
      .filter((row) => !recycled?.has(row.id))
      .sort((a, b) => a.id - b.id);
    errataListRef.current = ordered;
    setErrataList(ordered);
    const unseen = ordered.filter((row) => !popupSeenRef.current.has(row.id));
    const newest = unseen.length ? unseen[unseen.length - 1] : undefined;
    if (newest) setPopupId(newest.id);
  }, []);

  const persistSelection = (examId: number | null, nextBatchId: number | null) => {
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ examId, batchId: nextBatchId }));
  };

  const applyExam = useCallback((next: Exam | null, preferredBatchId?: number | null) => {
    setExam(next);
    if (!next) {
      setBatchId(null);
      batchIdRef.current = null;
      return;
    }
    const preferred = preferredBatchId ?? loadSelection().batchId;
    const found = next.batches.find((b) => b.id === preferred);
    const chosen = found?.id ?? next.batches[0]?.id ?? null;
    setBatchId(chosen);
    batchIdRef.current = chosen;
    persistSelection(next.id, chosen);
  }, []);

  const loadExam = useCallback(async (id: number, preferredBatchId?: number | null) => {
    const [next, current] = await Promise.all([
      examApi.retrieve(id),
      examApi.currentErrata(id).catch(() => ({ data: [] as ExamErrata[] })),
    ]);
    applyExam(next, preferredBatchId);
    ingestErrata(current.data ?? []);
    setDataSyncedAt(Date.now());
  }, [applyExam, ingestErrata]);

  const refresh = useCallback(async () => {
    const list = await examApi.list();
    setExams(list.results);
    const saved = loadSelection();
    const fallbackId = list.results[0]?.id ?? null;
    const targetId = list.results.some((e) => e.id === saved.examId) ? saved.examId : fallbackId;
    if (targetId == null) {
      applyExam(null);
      ingestErrata([]);
      setDataSyncedAt(Date.now());
      return;
    }
    const [examRow, current] = await Promise.all([
      examApi.retrieve(targetId),
      examApi.currentErrata(targetId).catch(() => ({ data: [] as ExamErrata[] })),
    ]);
    applyExam(examRow, saved.examId === targetId ? saved.batchId : null);
    ingestErrata(current.data ?? []);
    setDataSyncedAt(Date.now());
  }, [applyExam, ingestErrata]);

  const syncTime = useCallback(async () => {
    const sentAt = Date.now();
    try {
      const data = await examApi.clock();
      const receivedAt = Date.now();
      const rtt = Math.max(0, receivedAt - sentAt);
      timeOffsetRef.current = data.timestamp + rtt / 2 - receivedAt;
      setClockRttMs(Math.round(rtt));
      setClockSyncedAt(receivedAt);
    } catch {
      timeOffsetRef.current = 0;
    }
  }, []);

  useEffect(() => {
    api.me()
      .then((d) => setCanManage(!!d.user?.permissions?.can_manage_exam))
      .catch(() => setCanManage(false));
  }, [authNonce]);

  useLayoutEffect(() => {
    document.body.classList.add("exam-board-on");
    applyExamBoardMascotClass(loadExamBoardPrefs().mascot);
    return () => {
      document.body.classList.remove("exam-board-on");
      document.body.classList.remove("exam-board-hide-mascot");
    };
  }, []);

  useEffect(() => {
    document.title = "考试看板";
    refresh().catch(() => {});
    startExamBoardSocket();
    const stopStatus = onExamBoardSocketStatus(setSocketState);
    const stop = onExamBoardEvent((ev) => {
      if (ev.event === "exam") refresh().catch(() => {});
      if (ev.event === "errata") {
        const examId = loadSelection().examId;
        examApi.currentErrata(examId).then((r) => {
          ingestErrata(r.data ?? []);
          setDataSyncedAt(Date.now());
        }).catch(() => {});
      }
    });
    return () => {
      stop();
      stopStatus();
      stopExamBoardSocket();
    };
  }, [refresh, ingestErrata]);

  useEffect(() => {
    syncTime();
    const t = setInterval(syncTime, SYNC_INTERVAL);
    return () => clearInterval(t);
  }, [syncTime]);

  useEffect(() => {
    const tick = () => {
      const nowMs = Date.now() + timeOffsetRef.current;
      const { time } = shanghaiParts(nowMs);
      setCurrentTime(time);
      setStatus(matchBoard(batch?.subjects ?? [], nowMs));
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [batch]);

  const pendingFields = fieldsFromStatus(status, exam?.title || "暂无考试", batch?.name || "");
  const pendingKey = fieldKey(pendingFields);
  const pendingFieldsRef = useRef(pendingFields);
  pendingFieldsRef.current = pendingFields;

  useEffect(() => {
    if (pendingKey === fieldKeyRef.current) return;
    if (fadeTimerRef.current != null) window.clearTimeout(fadeTimerRef.current);
    setFade("out");
    fadeTimerRef.current = window.setTimeout(() => {
      const next = pendingFieldsRef.current;
      setFields(next);
      fieldKeyRef.current = fieldKey(next);
      setFade("in");
      fadeTimerRef.current = null;
    }, FADE_MS);
    return () => {
      if (fadeTimerRef.current != null) {
        window.clearTimeout(fadeTimerRef.current);
        fadeTimerRef.current = null;
      }
    };
  }, [pendingKey]);

  useEffect(() => {
    if (popupId == null) return;
    if (splashTimerRef.current != null) window.clearTimeout(splashTimerRef.current);
    splashTimerRef.current = window.setTimeout(() => {
      popupSeenRef.current.add(popupId);
      writePopupSeen(popupSeenRef.current);
      setPopupId(null);
      splashTimerRef.current = null;
    }, POPUP_MS);
    return () => {
      if (splashTimerRef.current != null) {
        window.clearTimeout(splashTimerRef.current);
        splashTimerRef.current = null;
      }
    };
  }, [popupId]);

  const recycleIds = useCallback(async (ids: number[]) => {
    if (!ids.length || recyclingRef.current) return;
    recyclingRef.current = true;
    for (const id of ids) {
      setErrataList((rows) => {
        const next = rows.filter((row) => row.id !== id);
        errataListRef.current = next;
        return next;
      });
      if (popupId === id) setPopupId(null);
      if (zoomed?.id === id) {
        const remain = liveErrataRef.current.filter((row) => row.id !== id);
        setZoomed(remain[0] ?? null);
      }
      await new Promise((resolve) => window.setTimeout(resolve, RECYCLE_GAP_MS));
    }
    recyclingRef.current = false;
  }, [popupId, zoomed?.id]);

  const closeGuide = () => {
    dismissGuide();
    setShowGuide(false);
  };

  const handleFullscreen = async () => {
    try {
      await togglePageFullscreen();
    } catch {
      /* browser may block if the click wasn't treated as a gesture */
    }
  };

  const cycleZoom = useCallback((dir = 1) => {
    const rows = liveErrataRef.current;
    if (!rows.length) return;
    setZoomed((current) => {
      if (rows.length === 1) return rows[0];
      const idx = current ? rows.findIndex((row) => row.id === current.id) : -1;
      const next = idx < 0 ? 0 : idx + dir;
      return rows[((next % rows.length) + rows.length) % rows.length];
    });
  }, []);

  useEffect(() => {
    const sync = () => setIsFullscreen(isPageFullscreen());
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  useEffect(() => {
    const stop = onExamBoardEvent((ev) => {
      if (ev.event !== "errata_cleared") return;
      const ids = Array.isArray(ev.payload.ids)
        ? ev.payload.ids.filter((n): n is number => typeof n === "number")
        : [];
      if (ids.length) void recycleIds(ids);
      else setErrataList([]);
    });
    return stop;
  }, [recycleIds]);

  const openSettings = () => {
    setTab("display");
    setSaveError("");
    if (exam) {
      const d = examToDraft(exam);
      setEditingId(exam.id);
      setDraftTitle(d.title);
      setDraftBatches(d.batches);
    } else {
      setEditingId(null);
      const d = emptyDraft();
      setDraftTitle(d.title);
      setDraftBatches(d.batches);
    }
    setIsModalOpen(true);
  };

  const startNewExam = () => {
    const d = emptyDraft();
    setEditingId(null);
    setDraftTitle(d.title);
    setDraftBatches(d.batches);
    setTab("edit");
  };

  const loadForEdit = async (id: number) => {
    const next = await examApi.retrieve(id);
    const d = examToDraft(next);
    setEditingId(next.id);
    setDraftTitle(d.title);
    setDraftBatches(d.batches);
    setTab("edit");
  };

  const handleSaveExam = async () => {
    const invalid = validateExamDraft(draftTitle, draftBatches);
    if (invalid) {
      setSaveError(invalid);
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      const payload = draftToPayload(draftTitle, draftBatches);
      const saved = editingId
        ? await examApi.update(editingId, payload)
        : await examApi.create(payload);
      await refresh();
      applyExam(saved, saved.batches[0]?.id ?? null);
      setIsModalOpen(false);
    } catch (e: any) {
      if (e?.apiError?.kind === "auth") {
        setIsModalOpen(false);
        openLogin();
        return;
      }
      setSaveError(e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handlePublishErrata = async () => {
    if (!exam) {
      setSaveError("请先选择一场考试");
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      const data = new FormData();
      data.append("exam", String(exam.id));
      if (batch) data.append("batch", String(batch.id));
      data.append("text", errataText);
      if (errataFile) data.append("image", errataFile);
      const published = await examApi.publishErrata(data);
      ingestErrata([...errataList.filter((row) => row.id !== published.id), published]);
      setErrataText("");
      setErrataFile(null);
      setIsModalOpen(false);
    } catch (e: any) {
      if (e?.apiError?.kind === "auth") {
        setIsModalOpen(false);
        openLogin();
        return;
      }
      setSaveError(e?.message || "发布失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDismissErrata = async () => {
    setSaving(true);
    try {
      const result = await examApi.dismissErrata(exam?.id);
      await recycleIds(result.ids ?? errataList.map((row) => row.id));
    } catch (e: any) {
      setSaveError(e?.message || "撤回失败");
    } finally {
      setSaving(false);
    }
  };

  const updatePrefs = (patch: Partial<ExamBoardPrefs>) => {
    const next = { ...prefs, ...patch };
    setPrefs(next);
    saveExamBoardPrefs(next);
    if (patch.mascot !== undefined) applyExamBoardMascotClass(patch.mascot);
  };

  const cue = cueFromStatus(status);
  const clockUrgent = status.kind === "active" && status.remainSec > 0 && status.remainSec <= WARN_SECONDS;
  const nowMs = Date.now() + timeOffsetRef.current;
  const viewStatus = matchBoard(batch?.subjects ?? [], nowMs);
  const recycled = batch?.id != null ? recycledByBatchRef.current.get(batch.id) : undefined;
  const liveErrata = viewStatus.kind === "active"
    ? errataList.filter((row) => errataStillLive(row, nowMs) && !recycled?.has(row.id))
    : [];
  liveErrataRef.current = liveErrata;
  const liveErrataKey = liveErrata.map((row) => row.id).join(",");
  const zoomCycling = zoomed != null && liveErrata.length > 1;

  useEffect(() => {
    const kind = cue?.kind ?? null;
    if (kind && kind !== prevCueKindRef.current) setZoomed(null);
    prevCueKindRef.current = kind;
  }, [cue?.kind]);

  useEffect(() => {
    for (const row of liveErrata) {
      if (!row.image_url) continue;
      const img = new Image();
      img.src = row.image_url;
    }
  }, [liveErrataKey]);

  useEffect(() => {
    if (!zoomed) return;
    if (liveErrataRef.current.some((row) => row.id === zoomed.id)) return;
    setZoomed(liveErrataRef.current[0] ?? null);
  }, [zoomed, liveErrataKey]);

  useEffect(() => {
    if (!zoomCycling) return;
    const timer = window.setInterval(() => {
      const rows = liveErrataRef.current;
      if (rows.length < 2) return;
      setZoomed((current) => {
        if (!current) return current;
        const idx = rows.findIndex((row) => row.id === current.id);
        return rows[(idx < 0 ? 0 : idx + 1) % rows.length];
      });
    }, ZOOM_CYCLE_MS);
    return () => window.clearInterval(timer);
  }, [zoomCycling, zoomed?.id]);

  useEffect(() => {
    errataListRef.current = errataList;
  }, [errataList]);

  useEffect(() => {
    batchIdRef.current = batchId;
  }, [batchId]);

  useEffect(() => {
    const now = Date.now() + timeOffsetRef.current;
    const kind = matchBoard(batch?.subjects ?? [], now).kind;
    const prev = paperKindRef.current;
    paperKindRef.current = kind;
    if (kind === "active") {
      if (prev !== "active") {
        setZoomed(null);
        setPopupId(null);
      }
      return;
    }
    const bid = batch?.id;
    const ids = errataListRef.current.map((row) => row.id);
    if (bid != null && ids.length) {
      const seen = recycledByBatchRef.current.get(bid) ?? new Set<number>();
      ids.forEach((id) => seen.add(id));
      recycledByBatchRef.current.set(bid, seen);
    }
    if (prev !== "active") return;
    setZoomed(null);
    setPopupId(null);
    examApi.currentErrata(exam?.id).catch(() => {});
  }, [currentTime, batch, exam?.id, errataList]);

  useEffect(() => {
    if (recyclingRef.current) return;
    const dead = errataList
      .filter((row) => !errataStillLive(row, Date.now() + timeOffsetRef.current))
      .map((row) => row.id);
    if (!dead.length) return;
    void recycleIds(dead);
    examApi.currentErrata(exam?.id).catch(() => {});
  }, [currentTime, errataList, exam?.id, recycleIds]);

  useEffect(() => {
    const say = (key: string, lines: string[], durationMs?: number, cueKind?: "errata" | "ending" | "approaching" | "done") => {
      if (spokenRef.current.has(key)) return;
      spokenRef.current.add(key);
      const text = pickLine(lines);
      if (prefs.mascot) speakMascot(text, durationMs);
      if (prefs.voice) speakExamVoice(text);
      if (prefs.sound && cueKind) playExamCue(cueKind);
    };
    const newest = liveErrata.length ? liveErrata[liveErrata.length - 1] : undefined;
    if (newest && popupId === newest.id) {
      say(`errata:${newest.id}`, ["题目有更正，请看左侧列表！", "有误刊，点一下就能放大"], 7000, "errata");
    } else if (cue?.kind === "ending") {
      say(`ending:${cue.subject}`, [
        `${cue.subject} 快结束了，检查一下有没有漏题～`,
        "还有一会儿就收卷了，抓紧时间哦",
      ], 5500, "ending");
    } else if (cue?.kind === "approaching") {
      say(`approach:${cue.subject}`, [
        `${cue.subject} 快开始了，准备进场吧`,
        "下一场要到了，收拾一下桌面～",
      ], 5500, "approaching");
    } else if (status.kind === "rest" && prevKindRef.current === "active") {
      say(`rest:${status.nextSubject}`, ["这科结束啦，休息一下再迎下一场", "先放松一下，下场还早着"]);
    } else if (status.kind === "done" && prevKindRef.current !== "done") {
      say("done", ["今天的考试都结束了，辛苦啦～", "收卷啦，大家辛苦了"], 5500, "done");
    } else if (status.kind === "active" && prefs.mascot) {
      say("hello", ["考试加油～看时间、看科目，有误刊我会喊你", "我在这儿盯着时间，大家安心作答～"]);
    }
    prevKindRef.current = status.kind;
  }, [liveErrata, popupId, cue?.kind, status.kind, prefs.mascot, prefs.sound, prefs.voice]);

    return (
    <div className={`exam-board-wrapper${isFullscreen ? " is-fullscreen" : ""}`} onClick={unlockExamBoardAudio}>
      <div className="board-tools">
        <button
          type="button"
          className={`board-tool${isFullscreen ? " is-on" : ""}`}
          onClick={handleFullscreen}
          title={isFullscreen ? "退出全屏" : "全屏投屏，适合教室大屏"}
        >
          {isFullscreen ? "退出全屏" : "全屏"}
        </button>
        <button
          type="button"
          id="settings-btn"
          className="board-tool"
          onClick={openSettings}
          title="选择考试批次、声音与题目误刊"
        >
          设置
        </button>
      </div>

      {showGuide && !isFullscreen && (
        <div className="board-guide" role="note">
          <p>教室投屏请点右上角「全屏」。有题目误刊时，点左侧卡片上的「放大」。多张会每分钟自动轮播。</p>
          <button type="button" className="board-guide-ok" onClick={closeGuide}>知道了</button>
        </div>
      )}

      {isModalOpen && (
        <div className="exam-settings-overlay" onClick={() => setIsModalOpen(false)}>
          <div className="exam-settings-panel" onClick={(e) => e.stopPropagation()}>
            <span className="close-btn" onClick={() => setIsModalOpen(false)}>&times;</span>
            <h3>考试看板设置</h3>
            <div className="settings-tabs">
              <button type="button" className={tab === "display" ? "active" : ""} onClick={() => setTab("display")}>显示批次</button>
              {canManage && (
                <>
                  <button type="button" className={tab === "edit" ? "active" : ""} onClick={() => setTab("edit")}>编辑考试</button>
                  <button type="button" className={tab === "errata" ? "active" : ""} onClick={() => setTab("errata")}>题目误刊</button>
                </>
              )}
            </div>

            {tab === "display" && (
              <div className="settings-body">
                <label>
                  考试
                  <select
                    value={exam?.id ?? ""}
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      if (!id) return;
                      loadExam(id).catch(() => {});
                    }}
                  >
                    {exams.length === 0 && <option value="">暂无考试</option>}
                    {exams.map((item) => (
                      <option key={item.id} value={item.id}>{item.title}</option>
                    ))}
                  </select>
                </label>
                <label>
                  批次
                  <select
                    value={batch?.id ?? ""}
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      setBatchId(id);
                      if (exam) persistSelection(exam.id, id);
                    }}
                  >
                    {(exam?.batches ?? []).map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </label>
                {batch && (
                  <ul className="subject-preview">
                    {batch.subjects.map((s) => (
                      <li key={s.id}>{s.exam_date} {s.name} {hm(s.start_time)}–{hm(s.end_time)}</li>
                    ))}
                    {batch.subjects.length === 0 && <li>该批次暂无科目</li>}
                  </ul>
                )}
                <label className="settings-check">
                  <input
                    type="checkbox"
                    checked={prefs.mascot}
                    onChange={(e) => updatePrefs({ mascot: e.target.checked })}
                  />
                  显示看板娘
                </label>
                <label className="settings-check">
                  <input
                    type="checkbox"
                    checked={prefs.sound}
                    onChange={(e) => updatePrefs({ sound: e.target.checked })}
                  />
                  提示音（收卷 / 下场 / 误刊）
                </label>
                <label className="settings-check">
                  <input
                    type="checkbox"
                    checked={prefs.voice}
                    onChange={(e) => updatePrefs({ voice: e.target.checked })}
                  />
                  语音播报
                </label>
                <p className="settings-hint">教室大屏请先点右上角「全屏」。有题目误刊时，点左侧「放大」给学生看；多张每分钟自动轮播。</p>
                <button type="button" className="btn-save" onClick={handleFullscreen}>
                  {isFullscreen ? "退出全屏" : "全屏投屏"}
                </button>
                <div className="board-health" aria-label="同步状态">
                  <div>
                    时钟同步 <strong>{formatSyncTime(clockSyncedAt)}</strong>
                    {clockRttMs != null && `（往返 ${clockRttMs} ms）`}
                  </div>
                  <div>课表同步 <strong>{formatSyncTime(dataSyncedAt)}</strong></div>
                  <div className={
                    socketState === "open" ? "is-ok" : socketState === "connecting" ? "is-wait" : "is-bad"
                  }>
                    推送 <strong>{socketStateLabel(socketState)}</strong>
                  </div>
                </div>
              </div>
            )}

            {tab === "edit" && canManage && (
              <div className="settings-body">
                <div className="edit-toolbar">
                  <select
                    value={editingId ?? ""}
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      if (id) loadForEdit(id).catch(() => {});
                    }}
                  >
                    <option value="">新建考试</option>
                    {exams.map((item) => (
                      <option key={item.id} value={item.id}>{item.title}</option>
                    ))}
                  </select>
                  <button type="button" className="btn-add" onClick={startNewExam}>+ 新建</button>
                </div>
                <label>
                  考试标题
                  <input value={draftTitle} onChange={(e) => setDraftTitle(e.target.value)} placeholder="如 2026 学年期末考试" />
                </label>
                {draftBatches.map((b, bi) => (
                  <div className="batch-editor" key={b.key}>
                    <div className="batch-head">
                      <input
                        value={b.name}
                        onChange={(e) => setDraftBatches(draftBatches.map((x, i) => i === bi ? { ...x, name: e.target.value } : x))}
                        placeholder="批次名称，如 高一"
                      />
                      <button
                        type="button"
                        className="btn-delete"
                        disabled={draftBatches.length <= 1}
                        onClick={() => setDraftBatches(draftBatches.filter((_, i) => i !== bi))}
                      >删除批次</button>
                    </div>
                    <table className="schedule-table">
                      <thead>
                        <tr>
                          <th>日期</th>
                          <th>科目</th>
                          <th>开始</th>
                          <th>结束</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {b.subjects.map((s, si) => (
                          <tr key={s.key} className={subjectRowInvalid(b, s) ? "row-invalid" : undefined}>
                            <td>
                              <input
                                type="date"
                                value={s.exam_date}
                                onChange={(e) => setDraftBatches(draftBatches.map((x, i) => i === bi ? {
                                  ...x,
                                  subjects: x.subjects.map((y, j) => j === si ? { ...y, exam_date: e.target.value } : y),
                                } : x))}
                              />
                            </td>
                            <td>
                              <input
                                value={s.name}
                                onChange={(e) => setDraftBatches(draftBatches.map((x, i) => i === bi ? {
                                  ...x,
                                  subjects: x.subjects.map((y, j) => j === si ? { ...y, name: e.target.value } : y),
                                } : x))}
                              />
                            </td>
                            <td>
                              <input
                                type="time"
                                value={s.start_time}
                                onChange={(e) => setDraftBatches(draftBatches.map((x, i) => i === bi ? {
                                  ...x,
                                  subjects: x.subjects.map((y, j) => j === si ? { ...y, start_time: e.target.value } : y),
                                } : x))}
                              />
                            </td>
                            <td>
                              <input
                                type="time"
                                value={s.end_time}
                                onChange={(e) => setDraftBatches(draftBatches.map((x, i) => i === bi ? {
                                  ...x,
                                  subjects: x.subjects.map((y, j) => j === si ? { ...y, end_time: e.target.value } : y),
                                } : x))}
                              />
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn-delete"
                                onClick={() => setDraftBatches(draftBatches.map((x, i) => i === bi ? {
                                  ...x,
                                  subjects: x.subjects.filter((_, j) => j !== si),
                                } : x))}
                              >
                                删
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <button
                      type="button"
                      className="btn-add"
                      onClick={() => setDraftBatches(draftBatches.map((x, i) => i === bi ? {
                        ...x,
                        subjects: [...x.subjects, { key: newKey(), name: "", exam_date: "", start_time: "09:00", end_time: "11:00" }],
                      } : x))}
                    >
                      + 添加科目
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-add"
                  onClick={() => setDraftBatches([...draftBatches, { key: newKey(), name: "", subjects: [] }])}
                >
                  + 添加批次
                </button>
                <p className="settings-hint">同一批次同一天的科目不能重叠；开始时间必须早于结束时间。相邻场次（结束=下场开始）可以。</p>
                {saveError && <p className="settings-error">{saveError}</p>}
                <div className="exam-settings-actions">
                  <button type="button" className="btn-save" disabled={saving} onClick={handleSaveExam}>
                    {saving ? "保存中…" : "保存到服务器"}
                  </button>
                </div>
              </div>
            )}

            {tab === "errata" && canManage && (
              <div className="settings-body">
                <p className="settings-hint">可连续发布多条。误刊出现在看板左侧列表，点卡片上的「放大」给学生看；放大后多条每分钟轮播。本场结束后按发布顺序依次收走。</p>
                <label>
                  说明
                  <textarea value={errataText} onChange={(e) => setErrataText(e.target.value)} rows={3} placeholder="如：语文第 3 题更正为……" />
                </label>
                <label>
                  图片
                  <input type="file" accept="image/jpeg,image/png,image/gif,image/webp" onChange={(e) => setErrataFile(e.target.files?.[0] ?? null)} />
                </label>
                {liveErrata.length > 0 && (
                  <ul className="subject-preview">
                    {liveErrata.map((row) => (
                      <li key={row.id}>{row.text || "图片误刊"}</li>
                    ))}
                  </ul>
                )}
                {saveError && <p className="settings-error">{saveError}</p>}
                <div className="exam-settings-actions">
                  {liveErrata.length > 0 && (
                    <button type="button" className="btn-delete" disabled={saving} onClick={handleDismissErrata}>撤回全部</button>
                  )}
                  <button type="button" className="btn-save" disabled={saving} onClick={handlePublishErrata}>广播误刊</button>
                </div>
              </div>
            )}

            {!canManage && tab !== "display" && (
              <p className="settings-hint">登录且持有「管理考试看板」后可编辑课表、广播误刊。</p>
            )}
          </div>
        </div>
      )}

      {zoomed && (
        <div className="errata-overlay errata-zoom" role="dialog" onClick={() => setZoomed(null)}>
          <div className="errata-zoom-box" onClick={(e) => e.stopPropagation()}>
            <div key={zoomed.id} className="errata-zoom-slide">
              <ErrataCard errata={zoomed} asButton={false} />
            </div>
            <div className="errata-zoom-bar">
              {liveErrata.length > 1 && (
                <span className="errata-zoom-meta">
                  {(liveErrata.findIndex((row) => row.id === zoomed.id) + 1) || 1} / {liveErrata.length}
                  {" · "}每分钟自动切换
                </span>
              )}
              {liveErrata.length > 1 && (
                <button type="button" className="errata-zoom-action" onClick={() => cycleZoom(1)}>
                  下一张
                </button>
              )}
              <button type="button" className="errata-zoom-action" onClick={() => setZoomed(null)}>
                关闭
              </button>
            </div>
            <p className="errata-zoom-dismiss-hint">也可点周围暗处取消</p>
          </div>
        </div>
      )}

      {cue && (
        <div className={`time-cue time-cue-${cue.kind}`} role="status">
          {cue.kind === "ending"
            ? `${cue.subject} 将在 ${formatRemain(cue.remainSec)} 后结束，请注意收卷时间`
            : `${cue.subject} 将于 ${cue.start} 开始，还有 ${formatRemain(cue.untilSec)}`}
        </div>
      )}

      {liveErrata.length > 0 && (
        <aside className="errata-rail" aria-label="题目误刊">
          <div className="errata-rail-head">
            <span>题目误刊</span>
            <button
              type="button"
              className="errata-zoom-open"
              onClick={() => setZoomed(liveErrata[0] ?? null)}
              title="放大查看，多张每分钟自动轮播"
            >
              放大
            </button>
          </div>
          <div className="errata-rail-list">
            {liveErrata.map((row) => (
              <ErrataCard
                key={row.id}
                errata={row}
                compact
                isNew={row.id === popupId}
                isZoomed={row.id === zoomed?.id}
                onOpen={setZoomed}
              />
            ))}
          </div>
        </aside>
      )}

      <ScheduleRail batch={batch} nowMs={nowMs} />

      <div className="board-container">
        <div className={`exam-heading board-fade ${fade}`}>
          <span id="exam-title">{fields.title}</span>
          {fields.batchName && <span id="exam-batch">{fields.batchName}</span>}
        </div>
        <div className="row1">
          <span id="current-time" className={clockUrgent ? "clock-urgent" : undefined}>{currentTime}</span>
        </div>
        <div className={`info-grid board-fade ${fade}`}>
          <div className="left-col">
            <span>当前科目：</span>
            <span id="current-subject">{fields.subject}</span>
          </div>
          <div className="right-col" id="start-time-container">
            <span>{fields.startCaption}</span>
            <span id="start-time">{fields.start}</span>
          </div>
        </div>
        <div className={`info-grid board-fade ${fade}`}>
          <div className="empty-col">
            {fields.restHint && <span className="rest-hint">{fields.restHint}</span>}
          </div>
          <div className="right-col" id="end-time-container">
            <span>结束时间：</span>
            <span id="end-time">{fields.end}</span>
          </div>
        </div>
      </div>
    </div>
  );
}