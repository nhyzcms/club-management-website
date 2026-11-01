import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import MemberResultCard, { type MemberPublicResult } from "../components/member/MemberResultCard";
import "../styles/member.css";

/**
 * 编号查询入口（`/#/v`）：摄像头扫工牌条码 + 手动输入，两条路进同一个端点
 * `/member/lookup/`（POST `{q}`）。
 *
 * 两条通道的口径不同：
 * - **12 位条码载荷**（6 位唯一键 + 6 位短签名）——签名即证明，**不消耗** 24 小时额度，
 *   现场连扫几十张工牌不会被挡；防枚举由 IP 频控兜底。
 * - **8 位识别码 / 真实姓名**——走首页「社员查询」那套按身份分档的额度（服务端判定）。
 *
 * 摄像头解码走 `barcode-detector`（iOS 没有原生 BarcodeDetector，必须 wasm 兜底）。
 * 它默认去 jsdelivr 取 wasm，国内基本取不到，所以这里用打包产物 URL 覆盖 locateFile。
 *
 * 深链接 `/#/v?q=<扫到的内容>`：Android 壳原生扫完条码/二维码后落到这里，
 * 自动填进输入框并查一次（`q` 变化才查，不重复消耗额度）。网页端不依赖它，
 * 手动粘贴这一串同样可用。
 */
export default function MemberLookupPage() {
  const [search] = useSearchParams();
  const preset = (search.get("q") || "").trim();
  /** 已经自动查过的 `q`：WebView 重新挂载 / 重渲染都不该重复查一次（会白扣额度）。 */
  const autoRef = useRef("");

  const [value, setValue] = useState("");
  const [results, setResults] = useState<MemberPublicResult[] | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
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

  // 离开页面时释放摄像头（iOS 上不释放会一直亮绿灯）。
  useEffect(() => stopCamera, [stopCamera]);

  const submit = useCallback(
    async (raw?: string) => {
      const query = (raw ?? value).replace(/[\s-]/g, "");
      if (!query || busy) return;
      setBusy(true);
      setNotice("");
      setResults(null);
      try {
        const data: any = await api.memberLookup(query);
        setResults((data?.results as MemberPublicResult[]) || []);
        if (!data?.found && data?.quota?.remaining !== undefined) {
          setNotice(`本次未命中，今日还可查 ${data.quota.remaining ?? 0} 次。`);
        }
      } catch (e: any) {
        const status = e?.status as number | undefined;
        if (status === 429) {
          setNotice(e?.message || "查询次数已达上限，请稍后再试。");
        } else if (status === 400) {
          setNotice("请输入真实姓名，或 8 位识别码 / 12 位条码内容。");
        } else {
          setNotice("查询失败，请稍后重试。");
        }
      } finally {
        setBusy(false);
      }
    },
    [busy, value],
  );

  // 深链接落地：App 原生扫码后把内容放进 `?q=`，这里替用户按一次「查询」。
  // 只认第一次出现的值（autoRef 去重）；用户随后改输入框手动查，不受影响。
  useEffect(() => {
    if (!preset || autoRef.current === preset) return;
    autoRef.current = preset;
    setValue(preset);
    void submit(preset);
  }, [preset, submit]);

  const startScan = useCallback(async () => {
    setScanError("");
    setNotice("");
    setResults(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setScanError("当前浏览器不支持调用摄像头，请手动输入编号。");
      return;
    }
    setScanning(true);
    try {
      // 解码器与 wasm 都按需加载：只有点了扫码才下载（wasm ~950KB，不进首屏）。
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
            setValue(raw);
            void submit(raw);
          }
        } catch {
          // 单帧解不出（对焦中 / 角度偏）不打断取景，下一帧再试。
        }
      }, 250);
    } catch (e: any) {
      stopCamera();
      const name = e?.name || "";
      if (name === "NotAllowedError") {
        setScanError("摄像头权限被拒绝——请在浏览器里允许本站使用摄像头，或手动输入编号。");
      } else if (name === "NotFoundError") {
        setScanError("没有找到可用摄像头，请手动输入编号。");
      } else if (name === "NotReadableError") {
        setScanError("摄像头被其他应用占用，请关掉后重试。");
      } else {
        setScanError("扫码组件加载失败，请手动输入编号。");
      }
    }
  }, [stopCamera, submit]);

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 460 }}>
          <div style={{ paddingTop: "var(--s-10)", paddingBottom: "var(--s-12)" }}>
            <div className="card card-pad">
              <h2 style={{ marginBottom: "var(--s-2)" }}>社员身份查询</h2>
              <p className="muted" style={{ marginBottom: "var(--s-5)" }}>
                拿工牌对准摄像头扫描条码，也可以手动输入编号。
              </p>

              {scanning ? (
                <div style={{ marginBottom: "var(--s-5)" }}>
                  <div className="member-scan-frame">
                    <video ref={videoRef} playsInline muted className="member-scan-video" />
                    <div className="member-scan-hint">把工牌条形码放进取景框，横向铺满</div>
                  </div>
                  <button type="button" className="btn btn-ghost btn-block" onClick={stopCamera}>
                    取消扫码
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary btn-block"
                  onClick={() => void startScan()}
                  style={{ marginBottom: "var(--s-4)" }}
                >
                  用摄像头扫工牌条码
                </button>
              )}

              {scanError && (
                <p className="muted" style={{ marginBottom: "var(--s-4)", color: "var(--danger, #c0392b)" }}>
                  {scanError}
                </p>
              )}

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void submit();
                }}
              >
                <label className="label" htmlFor="member-lookup-input">
                  或手动输入编号
                </label>
                <input
                  id="member-lookup-input"
                  className="input"
                  inputMode="text"
                  autoComplete="off"
                  maxLength={40}
                  placeholder="8 位识别码 / 12 位条码内容 / 真实姓名"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
                <p className="muted" style={{ fontSize: 12, marginTop: "var(--s-2)" }}>
                  扫工牌条码不计次数；手输识别码或姓名按每日额度计算。
                </p>
                <button
                  type="submit"
                  className="btn btn-secondary btn-block"
                  disabled={busy || !value.trim()}
                  style={{ marginTop: "var(--s-3)" }}
                >
                  {busy ? "查询中…" : "查询"}
                </button>
              </form>

              {notice && (
                <p className="muted" style={{ marginTop: "var(--s-4)" }}>
                  {notice}
                </p>
              )}

              {results && (
                <div className="center" style={{ marginTop: "var(--s-6)" }}>
                  {results.length > 0 ? (
                    <div>
                      {results.map((r) => (
                        <div key={r.code} className="member-lookup-result">
                          <MemberResultCard
                            result={r}
                            note="仅展示公开信息——电话、学号、邮箱不在查询范围内。"
                          />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">未找到匹配的社员身份——编号无效或不属于本社。</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
