import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api/client";
import MemberResultCard, { type MemberPublicResult } from "./MemberResultCard";
import type { MemberLookupQuota } from "./MemberLookup";
import { startCameraScan, scanImageFile, type ScanSession } from "./barcodeScanner";
import { parseScannedText } from "./scanPayload";
import "../../styles/member.css";

const ICON_SCAN = (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {/* 四角取景框 + 中间的条码 */}
    <path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3" />
    <path d="M7 8v8M10.5 8v8M14 8v8M17 8v8" />
  </svg>
);

const NOTE_VERIFY = "本页来自工牌二维码扫码，仅展示公开信息。";
const NOTE_LOOKUP = "本页来自工牌条形码查询，仅展示公开信息。";

type Status = "starting" | "scanning" | "loading" | "done" | "error";

interface Outcome {
  card: MemberPublicResult | null;
  note: string;
  empty: string;
}

/** DOMException → 人话（Chrome / Safari / 微信内置浏览器的 name 一致）。 */
function cameraErrorMessage(err: any): string {
  if (err?.message === "__no_media_devices__") {
    return "当前浏览器不支持调用摄像头（可能需要 HTTPS 或较新的浏览器），请改用「拍照 / 选图识别」。";
  }
  switch (err?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "摄像头权限被拒绝。请在浏览器设置里允许本站使用摄像头，或改用「拍照 / 选图识别」。";
    case "NotFoundError":
    case "OverconstrainedError":
      return "没有找到可用的摄像头，请改用「拍照 / 选图识别」。";
    case "NotReadableError":
      return "摄像头被其它应用占用，关闭占用它的应用后重试。";
    default:
      return "无法启动摄像头，请改用「拍照 / 选图识别」。";
  }
}

function hintFor(status: Status, count: number): string {
  switch (status) {
    case "starting":
      return "正在启动摄像头…";
    case "scanning":
      return "把工牌上的二维码或条形码对准取景框，识别后自动查询。";
    case "loading":
      return "已识别，正在查询社员信息…";
    case "done":
      return count > 0 ? "识别成功。" : "识别完成，但没有匹配到社员。";
    default:
      return "";
  }
}

/**
 * 首页「扫描条码」：扫工牌二维码 / 条形码 → 弹窗展示公开信息。
 *
 * 两条路径（见 scanPayload.ts）：
 * - 二维码带签名 → `/member/check/`，不扣查询额度；
 * - 条形码是裸识别码 → `/member/lookup/`，按查询者身份扣额度（额度与手输查询共用），
 *   所以查询完要把最新额度回传给外面的「今日还可查 N 次」提示。
 */
export default function MemberScanButton({
  onQuotaChange,
}: {
  onQuotaChange?: (quota: MemberLookupQuota | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>("starting");
  const [err, setErr] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [counting, setCounting] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const sessionRef = useRef<ScanSession | null>(null);
  const startingRef = useRef(false);
  /** 一张工牌只查一次：ZXing 会在多帧里重复回调同一段文本。 */
  const handledRef = useRef(false);

  const stopScan = useCallback(() => {
    sessionRef.current?.stop();
    sessionRef.current = null;
  }, []);

  const handleText = useCallback(
    async (raw: string) => {
      if (handledRef.current) return;
      handledRef.current = true;
      stopScan();
      // 扫码枪 / 手机都希望有个「滴」的手感；不支持的浏览器静默跳过。
      try {
        navigator.vibrate?.(30);
      } catch {
        /* 忽略 */
      }

      const payload = parseScannedText(raw);
      if (payload.kind === "unknown") {
        setStatus("error");
        setErr("识别到的内容不是本站工牌（既不是工牌二维码，也不是 8 位社员识别码）。");
        return;
      }

      setStatus("loading");
      setErr("");
      try {
        if (payload.kind === "verify") {
          try {
            const data: any = await api.memberCheck(payload.code, payload.sig);
            setOutcome({
              card: data?.found === false ? null : (data as MemberPublicResult),
              note: NOTE_VERIFY,
              empty: "工牌二维码无效、已失效或不属于本站。",
            });
          } catch (ex: any) {
            if (ex?.status === 404) {
              setOutcome({ card: null, note: NOTE_VERIFY, empty: "工牌二维码无效、已失效或不属于本站。" });
            }
            else throw ex;
          }
        } else {
          const data: any = await api.memberLookup(payload.code);
          const rows = (data?.results ?? []) as MemberPublicResult[];
          onQuotaChange?.((data?.quota ?? null) as MemberLookupQuota | null);
          setOutcome({
            card: rows[0] ?? null,
            note: NOTE_LOOKUP,
            empty: "未找到匹配的社员——请确认这张工牌是否属于本站。",
          });
        }
        setStatus("done");
      } catch (ex: any) {
        setStatus("error");
        // 429（额度用尽）/ 500 都带服务端中文原因，直接展示
        setErr(ex?.message || "查询失败，请稍后重试。");
      }
    },
    [onQuotaChange, stopScan],
  );

  const start = useCallback(async () => {
    if (startingRef.current) return;
    startingRef.current = true;
    handledRef.current = false;
    setOutcome(null);
    setErr("");
    setStatus("starting");
    try {
      const video = videoRef.current;
      if (!video) return;
      const session = await startCameraScan(video, (text) => {
        void handleText(text);
      });
      sessionRef.current = session;
      setStatus("scanning");
    } catch (ex: any) {
      setStatus("error");
      setErr(cameraErrorMessage(ex));
    } finally {
      startingRef.current = false;
    }
  }, [handleText]);

  const close = useCallback(() => {
    stopScan();
    setOpen(false);
  }, [stopScan]);

  // 打开即开始扫；关闭 / 卸载一定停掉摄像头。
  useEffect(() => {
    if (!open) return;
    void start();
    return () => stopScan();
  }, [open, start, stopScan]);

  // Esc 关闭（与「社员查询」弹窗行为一致）
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  const onPickImage = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // 允许重复选同一张图
    if (!file) return;
    setCounting(true);
    try {
      const text = await scanImageFile(file);
      if (!text) {
        setStatus("error");
        setErr("这张图里没识别到二维码或条形码，请换一张更清晰的照片。");
        return;
      }
      stopScan();
      void handleText(text);
    } catch {
      setStatus("error");
      setErr("图片识别失败，请稍后重试。");
    } finally {
      setCounting(false);
    }
  };

  const scanning = status === "starting" || status === "scanning";
  const resultCount = outcome?.card ? 1 : 0;

  return (
    <div className="member-scan">
      <button
        type="button"
        className="btn btn-primary btn-block member-scan-btn"
        onClick={() => setOpen(true)}
      >
        {ICON_SCAN}
        <span>扫描条码</span>
      </button>
      <p className="member-lookup-hint">对准工牌上的二维码或条形码，自动识别并显示公开信息。</p>

      {open && createPortal(
        <div
          className="modal-scrim is-open"
          role="dialog"
          aria-modal="true"
          aria-label="扫描工牌条码"
          style={{ zIndex: 10000 }}
          onClick={close}
        >
          <div className="modal member-scan-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h3>{status === "done" ? "扫描结果" : "扫描工牌条码"}</h3>
                <p>{hintFor(status, resultCount)}</p>
              </div>
              <button type="button" className="modal-close" aria-label="关闭" onClick={close}>
                ×
              </button>
            </div>

            <div className="modal-body">
              <div className={"member-scan-stage" + (scanning || status === "loading" ? "" : " is-hidden")}>
                <video
                  ref={videoRef}
                  className="member-scan-video"
                  muted
                  playsInline
                  autoPlay
                />
                {scanning && <div className="member-scan-frame" aria-hidden="true" />}
                {status === "loading" && <div className="member-scan-stage-note">查询中…</div>}
              </div>

              {status === "error" && (
                <p className="member-claim-err" role="alert">{err}</p>
              )}

              {status === "done" && (
                <div className="member-scan-result">
                  {outcome?.card ? (
                    <MemberResultCard result={outcome.card} note={outcome.note} />
                  ) : (
                    <p className="muted">{outcome?.empty}</p>
                  )}
                </div>
              )}
            </div>

            <div className="member-scan-actions">
              {status === "done" ? (
                <>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => void start()}>
                    再扫一个
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={close}>
                    完成
                  </button>
                </>
              ) : (
                <>
                  <label className={"btn btn-ghost btn-sm member-scan-file" + (counting ? " is-busy" : "")}>
                    {counting ? "识别中…" : "拍照 / 选图识别"}
                    <input
                      type="file"
                      accept="image/*"
                      aria-label="拍照或选择工牌照片识别"
                      onChange={(e) => void onPickImage(e)}
                      disabled={counting}
                    />
                  </label>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={close}>
                    取消
                  </button>
                </>
              )}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
