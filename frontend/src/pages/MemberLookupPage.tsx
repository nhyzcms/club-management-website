import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import MobilePage from "../components/MobilePage";
import MemberResultCard, { type MemberPublicResult } from "../components/member/MemberResultCard";
import { isMobileDevice } from "../utils/device";
import { useBarcodeScan } from "../hooks/useBarcodeScan";
import "../styles/member.css";
import "../styles/mobile.css";

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
  //
  // **只有 12 位条码载荷才自动查**：那条路签名即证明、不扣 24 小时额度。
  // 其它内容（8 位识别码 / 姓名）只预填输入框——否则一条 `/#/v?q=<别人的名字>`
  // 的链接就能替访问者把额度烧光（构造链接者不需要登录）。
  useEffect(() => {
    if (!preset || autoRef.current === preset) return;
    autoRef.current = preset;
    setValue(preset);
    if (/^\d{12}$/.test(preset)) void submit(preset);
  }, [preset, submit]);

  // 摄像头扫码与明信片登记/签收共用 `useBarcodeScan`：连续对焦、取景不裁切、
  // 解不出时只对解码器做中心放大（预览不放大）、支持轻点手动对焦。
  const scan = useBarcodeScan({
    onCode: (code) => {
      setValue(code);
      void submit(code);
    },
    label: "编号",
    appDeniedHint: "App 内没有拿到摄像头权限——请用右下角的「扫码」按钮，或手动输入编号。",
  });

  const startScan = useCallback(() => {
    setNotice("");
    setResults(null);
    void scan.start();
  }, [scan.start]);

  const isMobile = isMobileDevice();
  // 一套内容，两套外壳：桌面版挂在 AppShell 的卡片里，手机版挂在 /m 那套样式里。
  // 只换外壳不换逻辑，避免扫码/额度这套口径出现两份实现。
  const primaryBtn = isMobile ? "m-btn-primary" : "btn btn-primary btn-block";
  const ghostBtn = isMobile ? "m-btn-ghost" : "btn btn-ghost btn-block";
  const secondaryBtn = isMobile ? "m-btn-primary" : "btn btn-secondary btn-block";

  const body = (
    <>
      {!isMobile && (
        <h2 style={{ marginBottom: "var(--s-2)" }}>社员身份查询</h2>
      )}
      <p className="muted" style={{ marginBottom: "var(--s-5)" }}>
        拿工牌对准摄像头扫描条码，也可以手动输入编号。
      </p>

      {scan.scanning ? (
        <div style={{ marginBottom: "var(--s-5)" }}>
          <div
            className="member-scan-frame"
            style={scan.videoAspect ? { aspectRatio: String(scan.videoAspect) } : undefined}
            onPointerDown={(e) => scan.tapToFocus(e.clientX, e.clientY, e.currentTarget)}
          >
            <video ref={scan.videoRef} playsInline muted className="member-scan-video" />
            {scan.focusPoint && (
              <span
                className="member-scan-focus"
                style={{ left: `${scan.focusPoint.x * 100}%`, top: `${scan.focusPoint.y * 100}%` }}
              />
            )}
            <div className="member-scan-hint">条形码横向铺满取景框；轻点画面可手动对焦</div>
          </div>
          <button type="button" className={ghostBtn} onClick={scan.stop}>
            取消扫码
          </button>
        </div>
      ) : (
        <button
          type="button"
          className={primaryBtn}
          onClick={() => void startScan()}
          style={{ marginBottom: "var(--s-4)" }}
        >
          用摄像头扫工牌条码
        </button>
      )}

      {scan.error && (
        <p className="muted" style={{ marginBottom: "var(--s-4)", color: "var(--danger, #c0392b)" }}>
          {scan.error}
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
          className={secondaryBtn}
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
    </>
  );

  if (isMobile) {
    return (
      <MobilePage title="社员查询" back="/m">
        <section className="m-detail-sec" style={{ marginTop: 0 }}>{body}</section>
      </MobilePage>
    );
  }

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 460 }}>
          <div style={{ paddingTop: "var(--s-10)", paddingBottom: "var(--s-12)" }}>
            <div className="card card-pad">{body}</div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
