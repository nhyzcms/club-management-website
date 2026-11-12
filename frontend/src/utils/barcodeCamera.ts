/**
 * 摄像头扫码的约束与几何计算（纯函数，便于单测）。
 *
 * 背景（2026-11-12 用户反馈「扫码根本不能用：不对焦、画面被放大」）：
 * - 之前只给了 `facingMode`，没给分辨率、也没在拿到 track 后开连续对焦，
 *   很多机型会停在超焦距/单次触发，凑近拍 4cm 宽的条码就是糊的；
 * - 取景框写死 4:3 + `object-fit: cover`，手机/摄像头常见的 16:9 画面被裁掉两侧，
 *   视觉上就是「自动放大」，反而更难找到条码。
 *
 * 因此这里统一：请求够用的分辨率 → 按 `getCapabilities()` 开连续对焦、
 * 把变焦归位到最小（只归位，不主动放大）→ 取景用 contain 完整显示。
 */

/** 解码用的最长边：再高对 Code128 没有额外收益，只会拖慢低端机。 */
export const DECODE_MAX_SIDE = 1280;

/** 两次解码之间的间隔。用 setTimeout 串行，避免上一帧还没解完就叠下一帧。 */
export const DECODE_INTERVAL_MS = 200;

/** 全画面解不出时，中心裁切的比例（0.6 = 中间 60% 宽高）。 */
export const CENTER_CROP_SCALE = 0.6;

export type ZoomRange = { min: number; max: number; step: number };

/** 拿到 track 后的能力表（标准 TS 类型里没有 focusMode / zoom / pointsOfInterest）。 */
export type TrackCapabilities = {
  focusMode?: string[];
  exposureMode?: string[];
  zoom?: { min?: number; max?: number; step?: number };
  pointsOfInterest?: unknown;
};

/** 请求的摄像头参数：后摄 + 足够的分辨率。分辨率过高反而拖慢解码，1920 封顶。 */
export function buildVideoConstraints(): MediaTrackConstraints {
  return {
    facingMode: { ideal: "environment" },
    width: { ideal: 1920 },
    height: { ideal: 1080 },
    frameRate: { ideal: 30 },
  };
}

/** 读取硬件变焦范围；没有变焦能力（多数桌面 USB 摄像头）返回 null。 */
export function readZoomRange(caps: TrackCapabilities | null | undefined): ZoomRange | null {
  const zoom = caps?.zoom;
  const min = Number(zoom?.min);
  const max = Number(zoom?.max);
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null;
  const step = Number(zoom?.step);
  return { min, max, step: Number.isFinite(step) && step > 0 ? step : 0.1 };
}

/**
 * 进入扫码就要生效的约束（都放进 advanced：机型不支持时会被忽略，
 * 不会因为一条 OverconstrainedError 把整个取景打掉）。
 *
 * - `focusMode: continuous`：持续自动对焦，解决「凑近就糊」；
 * - `exposureMode: continuous`：顺带修一下灯光切换时的过曝/欠曝；
 * - `zoom: min`：把变焦归位到最广，避免沿用上一次的变焦（用户要的「不自动放大」）。
 */
export function buildFocusConstraints(caps: TrackCapabilities | null | undefined): Record<string, unknown>[] {
  if (!caps) return [];
  const set: Record<string, unknown> = {};
  if (Array.isArray(caps.focusMode) && caps.focusMode.includes("continuous")) {
    set.focusMode = "continuous";
  }
  if (Array.isArray(caps.exposureMode) && caps.exposureMode.includes("continuous")) {
    set.exposureMode = "continuous";
  }
  const zoom = readZoomRange(caps);
  if (zoom) set.zoom = zoom.min;
  return Object.keys(set).length ? [set] : [];
}

/**
 * 轻点画面手动对焦：`pointsOfInterest` 只在部分 Chromium（桌面 + 安卓）上支持，
 * 不支持的机型返回空数组（点一下没反应，但不报错）。
 */
export function pointOfInterestConstraints(
  caps: TrackCapabilities | null | undefined,
  x: number,
  y: number,
): Record<string, unknown>[] {
  if (!caps || !caps.pointsOfInterest) return [];
  const modes = Array.isArray(caps.focusMode) ? caps.focusMode : [];
  const set: Record<string, unknown> = {
    pointsOfInterest: [{ x: clamp01(x), y: clamp01(y) }],
  };
  if (modes.includes("single-shot")) set.focusMode = "single-shot";
  else if (modes.includes("continuous")) set.focusMode = "continuous";
  return [set];
}

/** 解码画布尺寸：不超过 DECODE_MAX_SIDE，且不放大（放大只是白烧 CPU）。 */
export function pickDecodeSize(
  width: number,
  height: number,
  maxSide = DECODE_MAX_SIDE,
): { width: number; height: number } {
  if (!(width > 0) || !(height > 0)) return { width: 0, height: 0 };
  const longest = Math.max(width, height);
  if (longest <= maxSide) return { width: Math.round(width), height: Math.round(height) };
  const ratio = maxSide / longest;
  return { width: Math.max(1, Math.round(width * ratio)), height: Math.max(1, Math.round(height * ratio)) };
}

/** 中心裁切区域（解码时把这块放大重绘，等价「对准后自动放大」，但不改预览）。 */
export function centerCropRect(
  width: number,
  height: number,
  scale = CENTER_CROP_SCALE,
): { x: number; y: number; width: number; height: number } {
  const s = Math.min(1, Math.max(0.1, scale));
  const w = Math.max(1, Math.round(width * s));
  const h = Math.max(1, Math.round(height * s));
  return { x: Math.round((width - w) / 2), y: Math.round((height - h) / 2), width: w, height: h };
}

/**
 * `object-fit: contain` 下画面在取景框里的实际位置。
 * 点击坐标要先映射回画面，换算成 `pointsOfInterest` 的 0–1 归一化坐标。
 */
export function containRect(
  boxWidth: number,
  boxHeight: number,
  mediaAspect: number | null | undefined,
): { x: number; y: number; width: number; height: number } {
  if (!(boxWidth > 0) || !(boxHeight > 0) || !mediaAspect || mediaAspect <= 0) {
    return { x: 0, y: 0, width: boxWidth, height: boxHeight };
  }
  const boxAspect = boxWidth / boxHeight;
  if (mediaAspect > boxAspect) {
    const height = boxWidth / mediaAspect;
    return { x: 0, y: (boxHeight - height) / 2, width: boxWidth, height };
  }
  const width = boxHeight * mediaAspect;
  return { x: (boxWidth - width) / 2, y: 0, width, height: boxHeight };
}

/** 点击位置 → 视频画面内的 0–1 坐标；点在黑边上则返回 null（不该抢对焦点）。 */
export function mapTapToVideoFraction(
  box: { left: number; top: number; width: number; height: number },
  mediaAspect: number | null | undefined,
  clientX: number,
  clientY: number,
): { x: number; y: number } | null {
  const inner = containRect(box.width, box.height, mediaAspect);
  if (!(inner.width > 0) || !(inner.height > 0)) return null;
  const x = (clientX - box.left - inner.x) / inner.width;
  const y = (clientY - box.top - inner.y) / inner.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { x, y };
}

/** 有的设备/输入法会在条码里插空白或连字符。 */
export function normalizeCode(raw: string | null | undefined): string {
  return (raw || "").replace(/[\s-]/g, "");
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0.5;
  return Math.min(1, Math.max(0, value));
}
