import { useCallback, useEffect, useRef, useState } from "react";
import { isAppShell } from "../utils/device";
import {
  buildFocusConstraints,
  buildVideoConstraints,
  centerCropRect,
  DECODE_INTERVAL_MS,
  mapTapToVideoFraction,
  normalizeCode,
  pickDecodeSize,
  pointOfInterestConstraints,
  type TrackCapabilities,
} from "../utils/barcodeCamera";

/**
 * 摄像头条码扫描（明信片条码 / 工牌条码共用）。
 *
 * 2026-11-12 用户反馈原来「扫码根本不能用」：不对焦、画面被自动放大。修复口径：
 * 1. 请求 1920 级别的分辨率（对焦与解码都需要像素密度）；
 * 2. 拿到 track 后按 `getCapabilities()` 开**连续自动对焦**、把变焦归位到最广；
 * 3. 取景框按视频真实宽高比 + `object-fit: contain`，完整显示不裁切；
 * 4. 轻点画面可手动对焦（支持的机型才生效）；
 * 5. 解码：全画面解不出时，中心 60% 裁切放大再试一次 —— 只放给解码器看，
 *    预览不动，等价于「对准条码后按需放大」，而不是一进来就放大。
 *
 * 解码链路仍是 `barcode-detector`（原生 BarcodeDetector，iOS 没有则 wasm 兜底）
 * + zxing-wasm 按需加载（~950KB 不进首屏，locateFile 指打包产物、不依赖 CDN）。
 */

type Detector = { detect: (source: CanvasImageSource) => Promise<Array<{ rawValue?: string }>> };

export type BarcodeScanOptions = {
  onCode: (code: string) => void;
  /** 手动输入什么：「条码号」/「编号」，用于拼错误提示。 */
  label: string;
  /** App 内拿不到摄像头权限时的完整提示（各页面口径不同）。 */
  appDeniedHint?: string;
};

export type BarcodeScanController = {
  scanning: boolean;
  error: string;
  /** 视频真实宽高比（`width / height`），取景框用来保持比例、不出黑边。 */
  videoAspect: number | null;
  /** 手动对焦的落点（取景框内 0–1 坐标），用来画对焦圈。 */
  focusPoint: { x: number; y: number } | null;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  start: () => Promise<void>;
  stop: () => void;
  tapToFocus: (clientX: number, clientY: number, box: HTMLElement | null) => void;
};

export function useBarcodeScan({ onCode, label, appDeniedHint }: BarcodeScanOptions): BarcodeScanController {
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [videoAspect, setVideoAspect] = useState<number | null>(null);
  const [focusPoint, setFocusPoint] = useState<{ x: number; y: number } | null>(null);

  const onCodeRef = useRef(onCode);
  onCodeRef.current = onCode;

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const detectorRef = useRef<Detector | null>(null);
  const timerRef = useRef<number | null>(null);
  const focusTimerRef = useRef<number | null>(null);
  const aliveRef = useRef(false);
  const busyRef = useRef(false);
  const videoAspectRef = useRef<number | null>(null);
  videoAspectRef.current = videoAspect;

  const stop = useCallback(() => {
    aliveRef.current = false;
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (focusTimerRef.current !== null) {
      window.clearTimeout(focusTimerRef.current);
      focusTimerRef.current = null;
    }
    busyRef.current = false;
    detectorRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setScanning(false);
    setFocusPoint(null);
  }, []);

  // 离开页面时释放摄像头（iOS 上不释放会一直亮绿灯）。
  useEffect(() => stop, [stop]);

  const start = useCallback(async () => {
    setError("");
    setFocusPoint(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(`当前浏览器不支持调用摄像头，请手动输入${label}。`);
      return;
    }
    setScanning(true);
    try {
      const [{ BarcodeDetector, prepareZXingModule }, wasmModule] = await Promise.all([
        import("barcode-detector"),
        import("zxing-wasm/reader/zxing_reader.wasm"),
      ]);
      await prepareZXingModule({
        overrides: { locateFile: () => wasmModule.default },
        fireImmediately: true,
      });
      detectorRef.current = new BarcodeDetector({ formats: ["code_128"] }) as unknown as Detector;

      const stream = await navigator.mediaDevices.getUserMedia({
        video: buildVideoConstraints(),
        audio: false,
      });
      // 对焦/曝光/变焦归位：不能因为机型不支持就挡掉取景，失败就保持默认。
      await tuneTrack(stream.getVideoTracks()[0]);

      const video = videoRef.current;
      if (!video) {
        stream.getTracks().forEach((track) => track.stop());
        setScanning(false);
        return;
      }
      const canvas = canvasRef.current || document.createElement("canvas");
      canvasRef.current = canvas;
      streamRef.current = stream;
      video.srcObject = stream;
      video.onloadedmetadata = () => {
        if (video.videoWidth && video.videoHeight) setVideoAspect(video.videoWidth / video.videoHeight);
      };
      await video.play();
      // loadedmetadata 可能在挂监听前就烧掉了，这里兜一下，保证取景框比例正确。
      if (video.videoWidth && video.videoHeight) setVideoAspect(video.videoWidth / video.videoHeight);
      // 等 play() 期间组件被卸载：ref 已被 React 置空，别把摄像头留在后台。
      if (!videoRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        setScanning(false);
        return;
      }
      aliveRef.current = true;

      function schedule() {
        if (!aliveRef.current) return;
        timerRef.current = window.setTimeout(() => void frame(), DECODE_INTERVAL_MS);
      }

      async function frame(): Promise<void> {
        if (!aliveRef.current) return;
        const detector = detectorRef.current;
        const current = videoRef.current;
        if (!detector || !current || current.readyState < 2 || !current.videoWidth) {
          schedule();
          return;
        }
        // 上一拍还没解完就跳过这一拍：低端机上叠帧只会越解越慢。
        if (busyRef.current) {
          schedule();
          return;
        }
        busyRef.current = true;
        let code = "";
        try {
          code = await decodeFrame(current, detector, canvasRef.current);
        } catch {
          // 单帧解不出（对焦中 / 角度偏）不打断取景，下一拍再试。
        } finally {
          busyRef.current = false;
        }
        if (!aliveRef.current) return;
        if (code) {
          stop();
          onCodeRef.current(code);
          return;
        }
        schedule();
      }

      void frame();
    } catch (e: any) {
      stop();
      const name = e?.name || "";
      if (name === "NotAllowedError") {
        setError(
          isAppShell()
            ? appDeniedHint || `App 内没有拿到摄像头权限——请手动输入${label}，或在浏览器中打开本页。`
            : `摄像头权限被拒绝——请在浏览器里允许本站使用摄像头，或手动输入${label}。`,
        );
      } else if (name === "NotFoundError") {
        setError(`没有找到可用摄像头，请手动输入${label}。`);
      } else if (name === "NotReadableError") {
        setError("摄像头被其他应用占用，请关掉后重试。");
      } else {
        setError(`扫码组件加载失败，请手动输入${label}。`);
      }
    }
  }, [appDeniedHint, label, stop]);

  const tapToFocus = useCallback((clientX: number, clientY: number, box: HTMLElement | null) => {
    const track = streamRef.current?.getVideoTracks()[0];
    if (!box || !track) return;
    const rect = box.getBoundingClientRect();
    const point = mapTapToVideoFraction(rect, videoAspectRef.current, clientX, clientY);
    if (!point) return; // 点在黑边上：不抢对焦点
    setFocusPoint(point);
    if (focusTimerRef.current !== null) window.clearTimeout(focusTimerRef.current);
    focusTimerRef.current = window.setTimeout(() => setFocusPoint(null), 700);
    let caps: TrackCapabilities | null = null;
    try {
      caps = (track.getCapabilities?.() as unknown as TrackCapabilities) || null;
    } catch {
      caps = null;
    }
    const advanced = pointOfInterestConstraints(caps, point.x, point.y);
    if (!advanced.length) return;
    void track.applyConstraints({ advanced } as MediaTrackConstraints).catch(() => {
      // 机型不支持点按对焦：忽略，靠连续对焦兜底。
    });
  }, []);

  return { scanning, error, videoAspect, focusPoint, videoRef, start, stop, tapToFocus };
}

async function tuneTrack(track: MediaStreamTrack | undefined): Promise<void> {
  if (!track || typeof track.applyConstraints !== "function") return;
  let caps: TrackCapabilities | null = null;
  try {
    caps = (track.getCapabilities?.() as unknown as TrackCapabilities) || null;
  } catch {
    return;
  }
  const advanced = buildFocusConstraints(caps);
  if (!advanced.length) return;
  try {
    await track.applyConstraints({ advanced } as MediaTrackConstraints);
  } catch {
    // 个别机型对 advanced 也报 OverconstrainedError：保持默认取景即可。
  }
}

/**
 * 解一帧：先整幅解，解不出再把中心 60% 放大重绘一次。
 * 第二次只影响喂给解码器的像素，预览画面不变 —— 用户要的「不自动放大」。
 */
async function decodeFrame(
  video: HTMLVideoElement,
  detector: Detector,
  canvas: HTMLCanvasElement | null,
): Promise<string> {
  if (!canvas) return "";
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  const sourceWidth = video.videoWidth;
  const sourceHeight = video.videoHeight;
  const size = pickDecodeSize(sourceWidth, sourceHeight);
  if (!size.width || !size.height) return "";

  canvas.width = size.width;
  canvas.height = size.height;
  ctx.drawImage(video, 0, 0, size.width, size.height);
  const whole = await detectOne(detector, canvas);
  if (whole) return whole;

  const crop = centerCropRect(sourceWidth, sourceHeight);
  ctx.drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, size.width, size.height);
  return detectOne(detector, canvas);
}

async function detectOne(detector: Detector, canvas: HTMLCanvasElement): Promise<string> {
  const codes = await detector.detect(canvas);
  for (const code of codes || []) {
    const raw = normalizeCode(code?.rawValue);
    if (raw) return raw;
  }
  return "";
}
