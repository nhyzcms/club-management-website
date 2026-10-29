/**
 * 浏览器端条码识别（摄像头 / 图片文件）。
 *
 * 为什么用 ZXing：除 Chrome / iOS Safari 之外的浏览器没有 `BarcodeDetector`（微信内置浏览器尤其没有），
 * 而工牌上既有二维码也有 Code128 条形码，只靠原生 API 会有一半设备扫不了。
 *
 * 为什么全部走动态 import：ZXing 压缩后几百 KB，而站点只有 3M 带宽。它只在用户真的点
 * 「扫描条码」时才下载，首屏和不扫码的访客零成本；webpack 会把它切成独立 chunk
 * （静态产物的缓存头是 1 年 immutable，第二次扫直接走缓存）。
 *
 * 识别格式锁定 QR + Code128 —— 工牌上就这两种（accounts/member_qr.py / member_barcode.py），
 * 收敛格式能让 ZXing 每帧少跑几轮解码，低端手机也跟得上。
 *
 * **只解取景框里的那一块**：实测把整帧（深色桌面 + 白工牌）交给 ZXing，Code128 会因为
 * 大面积高对比背景而二值化失败；裁到取景框（白卡占满画面）就稳定了。码比取景框还大
 * （怼得太近）时周期性用整帧兜底，两种构图都能识别。
 */

export interface ScanSession {
  stop: () => void;
}

/** 取景框内区域占画面的比例：与 CSS 里 `.member-scan-frame { inset: 14% }` 对齐。 */
const CROP_RATIO = 0.72;
/** 两帧之间的间隔：低端手机跑满帧只会发热掉电，180ms 足够跟手。 */
const SCAN_INTERVAL_MS = 180;
/** 每隔几帧用整帧兜底一次（码比取景框大时用得上）。 */
const FULL_FRAME_EVERY = 3;
/** 整帧兜底时先缩到这个宽度内：1D 解码对超大图收益不大，反而更慢。 */
const FULL_FRAME_MAX_W = 1000;

/** 载入 ZXing 并构造一个只认 QR + Code128 的 reader。 */
async function loadReader(): Promise<any> {
  const [browser, library] = await Promise.all([
    import("@zxing/browser"),
    import("@zxing/library"),
  ]);
  const { BrowserMultiFormatReader, BarcodeFormat } = browser;
  const { DecodeHintType } = library;

  const hints = new Map<number, unknown>();
  hints.set(DecodeHintType.POSSIBLE_FORMATS, [BarcodeFormat.QR_CODE, BarcodeFormat.CODE_128]);

  return new BrowserMultiFormatReader(hints);
}

/** 解一次；解不出来（NotFoundException）返回空串，不抛错。 */
function decodeOnce(reader: any, canvas: HTMLCanvasElement): string {
  try {
    const result = reader.decodeFromCanvas(canvas);
    return String(result?.getText?.() ?? "").trim();
  } catch {
    return "";
  }
}

/**
 * 打开摄像头并把识别到的文本交给 `onText`（同一段文本会被回调多次，调用方负责去重）。
 *
 * 失败（无摄像头 / 拒绝授权 / 被占用）时抛出原始 DOMException，由调用方翻译成中文提示。
 */
export async function startCameraScan(
  video: HTMLVideoElement,
  onText: (text: string) => void,
): Promise<ScanSession> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("__no_media_devices__");
  }

  // 先自己拿流再交给 ZXing：这样关闭时一定能关掉摄像头指示灯。
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
  });

  const reader = await loadReader();
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let frame = 0;

  video.srcObject = stream;
  video.muted = true;
  video.playsInline = true;
  try {
    await video.play();
  } catch {
    /* 个别浏览器要等一次手势才播；画面已经在流里，下一帧重试即可 */
  }

  const crop = document.createElement("canvas");
  const full = document.createElement("canvas");

  const tick = () => {
    if (stopped) return;
    const vw = video.videoWidth || 0;
    const vh = video.videoHeight || 0;
    if (!vw || !vh) {
      // 首帧还没解码出尺寸（刚拿到流时常见），稍后再试
      timer = setTimeout(tick, 120);
      return;
    }

    const cw = Math.max(1, Math.round(vw * CROP_RATIO));
    const ch = Math.max(1, Math.round(vh * CROP_RATIO));
    crop.width = cw;
    crop.height = ch;
    crop
      .getContext("2d")
      ?.drawImage(video, Math.round((vw - cw) / 2), Math.round((vh - ch) / 2), cw, ch, 0, 0, cw, ch);

    let text = decodeOnce(reader, crop);
    if (!text && frame % FULL_FRAME_EVERY === 0) {
      const scale = Math.min(1, FULL_FRAME_MAX_W / vw);
      full.width = Math.round(vw * scale);
      full.height = Math.round(vh * scale);
      full.getContext("2d")?.drawImage(video, 0, 0, full.width, full.height);
      text = decodeOnce(reader, full);
    }
    frame += 1;

    if (text) onText(text);
    timer = setTimeout(tick, SCAN_INTERVAL_MS);
  };
  timer = setTimeout(tick, 0);

  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (timer) clearTimeout(timer);
    stream.getTracks().forEach((track) => track.stop());
    if (video.srcObject === stream) video.srcObject = null;
  };

  return { stop };
}

/**
 * 从一张工牌照片里识别条码（摄像头不可用时的兜底，也方便在电脑上用截图试）。
 * 返回识别到的文本；识别不出来返回 null（不抛错，调用方统一提示）。
 */
export async function scanImageFile(file: File): Promise<string | null> {
  const reader = await loadReader();
  const url = URL.createObjectURL(file);
  try {
    const result = await reader.decodeFromImageUrl(url);
    const text = String(result?.getText?.() ?? "").trim();
    return text || null;
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}
