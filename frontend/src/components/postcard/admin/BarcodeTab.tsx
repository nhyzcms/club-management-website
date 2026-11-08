import { useCallback, useEffect, useState } from "react";
import {
  downloadWithCredentials,
  postcardAdminApi,
  type BarcodeSummary,
} from "../../../api/postcardAdmin";
import { clampBarcodeCount, errMessage, isForbidden } from "./pure";

/** 条码：生成（1500~10000、步进 500）与整版 PDF 导出。 */
export default function BarcodeTab() {
  const [summary, setSummary] = useState<BarcodeSummary | null>(null);
  const [count, setCount] = useState(6000);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await postcardAdminApi.barcodes();
      setSummary(d);
      // 默认值只在首次加载时填充，避免生成后把用户选的数量重置。
      setCount((prev) => (prev === 6000 && d.default ? d.default : prev));
    } catch (e) {
      setError(isForbidden(e) ? "需要 manage_postcard 权限。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const total = summary?.total ?? 0;
  const min = summary?.min ?? 1500;
  const max = summary?.max ?? 10000;
  const step = summary?.step ?? 500;

  const generate = async () => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const d = await postcardAdminApi.generateBarcodes(clampBarcodeCount(count, min, max, step));
      setNotice(`已生成 ${d.generated} 个条码，当前共 ${d.total} 个。`);
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const downloadPdf = async () => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await downloadWithCredentials(
        postcardAdminApi.barcodePdfUrl(),
        `明信片条码-${new Date().toISOString().slice(0, 10)}.pdf`,
      );
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="pa-muted">加载中…</p>;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}
      {notice && <p className="pa-ok">{notice}</p>}

      <section className="pa-card">
        <h3 className="pa-card-title">当前条码</h3>
        <p className="pa-big tnum">{total}</p>
        <p className="pa-hint">
          单活动累计不超过 {max} 个；条码为 7 位随机数字，Code-128，整版 PDF 为 A4 / 40×20mm / 2mm
          间隙（每页 65 枚）。
        </p>
      </section>

      <section className="pa-card">
        <h3 className="pa-card-title">生成条码</h3>
        <div className="pa-inline">
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            aria-label="生成数量"
          />
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void generate()}>
            {busy ? "处理中…" : "生成"}
          </button>
        </div>
        <p className="pa-hint">
          范围 {min}~{max}，步进 {step}；已生成的条码不会被覆盖，再次生成是追加。
        </p>
      </section>

      <section className="pa-card">
        <h3 className="pa-card-title">导出</h3>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={busy || total === 0}
          onClick={() => void downloadPdf()}
        >
          下载整版 PDF
        </button>
        {total === 0 && <p className="pa-hint">先生成条码再导出。</p>}
      </section>
    </div>
  );
}
