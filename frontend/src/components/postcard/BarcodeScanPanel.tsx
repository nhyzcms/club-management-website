import { useCallback, useEffect, useRef, useState } from "react";
import { isAppShell } from "../../utils/device";

/**
 * 明信片条码扫码面板：摄像头扫明信片上的 7 位 Code128 条码。
 *
 * 解码链路与「社员查询」（MemberLookupPage）一致：`barcode-detector`
 * （原生 BarcodeDetector，iOS 没有必须 wasm 兜底）+ zxing-wasm 按需加载
 * （wasm ~950KB 不进首屏；locateFile 指向打包产物，不依赖 jsdelivr CDN）。
 * 命中即停机回调 `onCode`，由父组件决定加不加入登记列表（查重 / 上限）。
 */
export default function BarcodeScanPanel({ onCode }: { onCode: (code: string) => void }) {
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState("");

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  const aliveRef = useRef(false);

  const stopCamera = useCallback(() => {
    aliveRef.current = false;
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setScanning(false);
  }, []);

  // 离开面板时释放摄像头（iOS 上不释放会一直亮绿灯）。
  useEffect(() => stopCamera, [stopCamera]);

  const startScan = useCallback(async () => {
    setScanError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setScanError("当前浏览器不支持调用摄像头，请手动输入条码号。");
      return;
    }
    setScanning(true);
    try {
      const [{ BarcodeDetector, prepareZXingModule }, wasmModule] = await Promise.all([
        import("barcode-detector"),
        import("zxing-wasm/reader/zxing_reader.wasm"),
      ]);
      const wasmUrl = wasmModule.default;
      await prepareZXingModule({
        overrides: { locateFile: () => wasmUrl },
        fireImmediately: true,
      });
      const detector = new BarcodeDetector({ formats: ["code_128"] });
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      if (!videoRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        setScanning(false);
        return;
      }
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      aliveRef.current = true;
      timerRef.current = window.setInterval(async () => {
        if (!aliveRef.current || !videoRef.current || videoRef.current.readyState < 2) return;
        try {
          const codes = await detector.detect(videoRef.current);
          const raw = (codes[0]?.rawValue || "").replace(/[\s-]/g, "");
          if (raw) {
            stopCamera();
            onCode(raw);
          }
        } catch {
          // 单帧解不出（对焦中 / 角度偏）不打断取景，下一帧再试。
        }
      }, 250);
    } catch (e: any) {
      stopCamera();
      const name = e?.name || "";
      if (name === "NotAllowedError") {
        setScanError(
          isAppShell()
            ? "App 内没有拿到摄像头权限——请用系统相机拍下条码后手动输入，或在浏览器中打开本页。"
            : "摄像头权限被拒绝——请在浏览器里允许本站使用摄像头，或手动输入条码号。",
        );
      } else if (name === "NotFoundError") {
        setScanError("没有找到可用摄像头，请手动输入条码号。");
      } else if (name === "NotReadableError") {
        setScanError("摄像头被其他应用占用，请关掉后重试。");
      } else {
        setScanError("扫码组件加载失败，请手动输入条码号。");
      }
    }
  }, [stopCamera, onCode]);

  if (!scanning) {
    return (
      <div className="pc-scan-entry">
        <button type="button" className="btn btn-secondary" onClick={() => void startScan()}>
          用摄像头扫明信片条码
        </button>
        {scanError && <p className="pc-scan-error">{scanError}</p>}
      </div>
    );
  }

  return (
    <div className="pc-scan-live">
      <div className="pc-scan-frame">
        <video ref={videoRef} playsInline muted className="pc-scan-video" />
        <div className="pc-scan-hint">把明信片上的条形码放进取景框，横向铺满</div>
      </div>
      <button type="button" className="btn btn-ghost" onClick={stopCamera}>
        取消扫码
      </button>
      {scanError && <p className="pc-scan-error">{scanError}</p>}
    </div>
  );
}
