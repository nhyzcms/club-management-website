import { useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import MobilePage from "../components/MobilePage";
import BarcodeScanPanel from "../components/postcard/BarcodeScanPanel";
import { postcardAdminApi, type ReceiptPayload } from "../api/postcardAdmin";
import { errMessage, fmtTime } from "../components/postcard/admin/pure";
import { isMobileDevice } from "../utils/device";
import "../styles/postcard-admin.css";
import { enterSim, isSimMode, isSimRoute } from "../postcardSim/session";

/**
 * 签收扫码（`/#/postcard/receive`）：扫明信片上的 7 位 Code-128 或手填条码。
 *
 * 命中 → 展示登记单信息 → 确认后该张置「已报寄」（联动登记单状态）；
 * 未命中 → 后端固定文案「明信片未登记，请先登记！」。
 * 误签可回退（已报寄 → 已登记），同样留审计。
 */
export default function PostcardReceivePage() {
  // 模拟环境（?sim=1）：渲染期装载内存沙箱；幂等，且必须早于子组件的 effect。
  if (isSimRoute()) enterSim();
  const isMobile = isMobileDevice();
  const [barcode, setBarcode] = useState("");
  const [payload, setPayload] = useState<ReceiptPayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string[]>([]);

  useEffect(() => {
    document.title = "明信片签收 · 南汇一中传媒社";
  }, []);

  const lookup = async (code: string) => {
    const value = code.trim();
    if (!/^\d{7}$/.test(value)) {
      setError("请输入 7 位条码号。");
      setPayload(null);
      return;
    }
    setBusy(true);
    setError("");
    try {
      setPayload(await postcardAdminApi.lookup(value));
    } catch (e) {
      setPayload(null);
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const act = async (kind: "confirm" | "unreport") => {
    if (!payload) return;
    setBusy(true);
    setError("");
    try {
      const d =
        kind === "confirm"
          ? await postcardAdminApi.confirm(payload.barcode)
          : await postcardAdminApi.unreport(payload.barcode);
      setPayload(d);
      if (kind === "confirm") {
        setDone((prev) => [payload.barcode, ...prev.filter((b) => b !== payload.barcode)].slice(0, 20));
      }
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const body = (
    <div className="pa-page pa-receive">
      <header className="pa-head">
        <div>
          <h1 className="pa-title">明信片签收</h1>
          <p className="pa-sub">
            扫明信片上的条码，核对信息后确认签收。
            <a className="pa-inline-link" href={isSimMode() ? "#/postcard/admin?sim=1" : "#/postcard/admin"}>
              返回管理端
            </a>
          </p>
        </div>
      </header>

      <section className="pa-card">
        <div className="pa-inline">
          <input
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={7}
            placeholder="7 位条码号"
            value={barcode}
            onChange={(e) => setBarcode(e.target.value.replace(/\D/g, "").slice(0, 7))}
            onKeyDown={(e) => {
              if (e.key === "Enter") void lookup(barcode);
            }}
            aria-label="条码号"
          />
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void lookup(barcode)}>
            {busy ? "查询中…" : "查询"}
          </button>
        </div>
        <BarcodeScanPanel
          onCode={(code) => {
            setBarcode(code);
            void lookup(code);
          }}
        />
      </section>

      {error && <p className="pa-error">{error}</p>}

      {payload && (
        <section className="pa-card pa-receipt">
          <div className="pa-receipt-head">
            <span className="pa-badge tnum">{payload.barcode}</span>
            <span className={`pa-pill ${payload.item_status === "reported" ? "is-ok" : ""}`}>
              {payload.item_status_label || "—"}
            </span>
            {payload.already_reported && <span className="pa-muted">此前已签收</span>}
          </div>
          <dl className="pa-dl">
            <div>
              <dt>寄出人</dt>
              <dd>
                {payload.registration.sender_name} · {payload.registration.grade_label}
                {payload.registration.class_no}班
              </dd>
            </div>
            <div>
              <dt>寄达</dt>
              <dd>
                {payload.registration.dest_region} {payload.registration.dest_school}
              </dd>
            </div>
            <div>
              <dt>登记码</dt>
              <dd className="tnum">{payload.registration.reg_code}</dd>
            </div>
            <div>
              <dt>登记时间</dt>
              <dd>{fmtTime(payload.registration.created_at)}</dd>
            </div>
          </dl>
          <div className="pa-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || payload.item_status === "reported" || payload.item_status === "cancelled"}
              onClick={() => void act("confirm")}
            >
              确认签收
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy || payload.item_status !== "reported"}
              onClick={() => void act("unreport")}
            >
              误签回退
            </button>
          </div>
          {payload.item_status === "cancelled" && (
            <p className="pa-hint">该明信片所属登记已取消，无法签收。</p>
          )}
        </section>
      )}

      {done.length > 0 && (
        <section className="pa-card">
          <h3 className="pa-card-title">本次已签收（{done.length}）</h3>
          <p className="pa-chips">
            {done.map((b) => (
              <span key={b} className="pa-chip tnum">
                {b}
              </span>
            ))}
          </p>
        </section>
      )}
    </div>
  );

  if (isMobile) {
    return (
      <MobilePage title="明信片签收" back="/postcard/admin">
        {body}
      </MobilePage>
    );
  }
  return (
    <AppShell>
      <div className="page">
        <div className="container pa-container">{body}</div>
      </div>
    </AppShell>
  );
}
