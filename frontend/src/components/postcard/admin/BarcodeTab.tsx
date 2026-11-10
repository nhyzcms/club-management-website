import { useCallback, useEffect, useState } from "react";
import {
  downloadWithCredentials,
  postcardAdminApi,
  type BarcodeSummary,
} from "../../../api/postcardAdmin";
import ConfirmModal from "../../../components/ConfirmModal";
import { clampBarcodeCount, errMessage, isForbidden } from "./pure";

/** 条码：生成（1500~10000、步进 500）、覆盖重建与整版 PDF 导出。 */
export default function BarcodeTab() {
  const [summary, setSummary] = useState<BarcodeSummary | null>(null);
  const [count, setCount] = useState(6000);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmReplace, setConfirmReplace] = useState(false);

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
  const bound = summary?.bound ?? 0;
  const min = summary?.min ?? 1500;
  const max = summary?.max ?? 10000;
  const step = summary?.step ?? 500;
  const remaining = Math.max(0, max - total);

  const bump = (direction: 1 | -1) => {
    setCount((prev) => Math.min(max, Math.max(min, prev + direction * step)));
  };

  const generate = async (replace: boolean) => {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const d = await postcardAdminApi.generateBarcodes(
        clampBarcodeCount(count, min, max, step),
        replace,
      );
      setNotice(
        replace
          ? `已覆盖重建：新生成 ${d.generated} 个条码，当前共 ${d.total} 个。`
          : `已生成 ${d.generated} 个条码，当前共 ${d.total} 个。`,
      );
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
      setConfirmReplace(false);
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
          <div className="pa-stepper" role="group" aria-label="生成数量">
            <button
              type="button"
              className="pa-step-btn"
              aria-label={`减少 ${step} 个`}
              disabled={busy || count <= min}
              onClick={() => bump(-1)}
            >−</button>
            <span className="pa-step-value tnum" aria-live="polite">{count}</span>
            <button
              type="button"
              className="pa-step-btn"
              aria-label={`增加 ${step} 个`}
              disabled={busy || count >= max}
              onClick={() => bump(1)}
            >+</button>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || remaining <= 0 || count > remaining}
            onClick={() => void generate(false)}
          >
            {busy ? "处理中…" : total === 0 ? "生成条码" : "继续生成条码"}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={busy || total === 0 || bound > 0}
            onClick={() => setConfirmReplace(true)}
          >
            覆盖生成新条码
          </button>
        </div>
        <p className="pa-hint">
          数量 {min}~{max}，按 {step} 递增；「继续生成」是追加，不覆盖已生成的条码。
          单活动累计不超过 {max} 个，当前还可生成 {remaining} 个。
        </p>
        {bound > 0 && (
          <p className="pa-hint">
            已有 {bound} 个条码被登记占用（已张贴/发出），因此不能覆盖重建。
          </p>
        )}
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

      {confirmReplace && (
        <ConfirmModal
          title="覆盖生成新条码？"
          confirmLabel="覆盖生成"
          danger
          busy={busy}
          onCancel={() => setConfirmReplace(false)}
          onConfirm={() => void generate(true)}
        >
          <p>
            将删除当前 <b className="tnum">{total}</b> 个尚未被登记使用的条码，并重新生成{" "}
            <b className="tnum">{count}</b> 个新条码。
          </p>
          <p style={{ marginTop: 8 }}>
            已下载 / 已打印的旧条码整版 PDF 随之作废，贴出去的旧条码将无法登记。此操作不可撤销。
          </p>
        </ConfirmModal>
      )}
    </div>
  );
}
