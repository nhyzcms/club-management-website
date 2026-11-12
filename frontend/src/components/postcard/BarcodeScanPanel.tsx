import { useBarcodeScan } from "../../hooks/useBarcodeScan";

/**
 * 明信片条码扫码面板：摄像头扫明信片上的 7 位 Code128 条码。
 *
 * 摄像头细节（连续对焦、变焦归位、按需中心放大解码、点按对焦）都在
 * `useBarcodeScan` 里，与「社员查询」（MemberLookupPage）共用一套实现。
 * 命中即停机回调 `onCode`，由父组件决定加不加入登记列表（查重 / 上限）。
 */
export default function BarcodeScanPanel({ onCode }: { onCode: (code: string) => void }) {
  const scan = useBarcodeScan({
    onCode,
    label: "条码号",
    appDeniedHint: "App 内没有拿到摄像头权限——请用系统相机拍下条码后手动输入，或在浏览器中打开本页。",
  });

  if (!scan.scanning) {
    return (
      <div className="pc-scan-entry">
        <button type="button" className="btn btn-secondary" onClick={() => void scan.start()}>
          用摄像头扫明信片条码
        </button>
        {scan.error && <p className="pc-scan-error">{scan.error}</p>}
      </div>
    );
  }

  return (
    <div className="pc-scan-live">
      <div
        className="pc-scan-frame"
        // 按视频真实宽高比撑开，配合 contain：画多少显示多少，不裁切也不放大。
        style={scan.videoAspect ? { aspectRatio: String(scan.videoAspect) } : undefined}
        onPointerDown={(e) => scan.tapToFocus(e.clientX, e.clientY, e.currentTarget)}
      >
        <video ref={scan.videoRef} playsInline muted className="pc-scan-video" />
        {scan.focusPoint && (
          <span
            className="pc-scan-focus"
            style={{ left: `${scan.focusPoint.x * 100}%`, top: `${scan.focusPoint.y * 100}%` }}
          />
        )}
        <div className="pc-scan-hint">条形码横向铺满取景框；轻点画面可手动对焦</div>
      </div>
      <button type="button" className="btn btn-ghost" onClick={scan.stop}>
        取消扫码
      </button>
      {scan.error && <p className="pc-scan-error">{scan.error}</p>}
    </div>
  );
}
