import { useEffect, useState } from "react";
import { api } from "../api/client";
import { reportsApi } from "../api/reports";
import type { ReportTargetType } from "../types/reports";

export default function ReportButton({
  targetType,
  targetId,
  isOwn,
  ownerId,
  compact,
}: {
  targetType: ReportTargetType;
  targetId: number;
  isOwn?: boolean;
  ownerId?: number;
  compact?: boolean;
}) {
  const [verified, setVerified] = useState(false);
  const [selfId, setSelfId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.me()
      .then((d: any) => {
        setVerified(!!d.profile?.is_verified);
        setSelfId(d.user?.id ?? null);
      })
      .catch(() => { setVerified(false); setSelfId(null); });
  }, []);

  const own = isOwn || (ownerId != null && selfId != null && ownerId === selfId);
  if (!verified || own || done) {
    if (done) return <span className="muted">已举报</span>;
    return null;
  }

  const submit = async () => {
    const r = reason.trim();
    if (!r) { setError("请填写举报理由"); return; }
    setBusy(true);
    setError("");
    try {
      await reportsApi.file({ target_type: targetType, target_id: targetId, reason: r });
      setDone(true);
      setOpen(false);
    } catch (e: any) {
      setError(e.message || "提交失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="report-ctl">
      <button
        className={compact ? "btn btn-ghost btn-sm" : "btn btn-ghost"}
        type="button"
        onClick={() => setOpen((v) => !v)}
      >
        举报
      </button>
      {open && (
        <div className="card card-pad" style={{ marginTop: 8, maxWidth: 360 }}>
          {error && <div className="alert alert-danger" style={{ marginBottom: 8 }}><span>{error}</span></div>}
          <label className="label">举报理由</label>
          <textarea
            className="textarea"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="请说明原因"
          />
          <div className="detail-row" style={{ marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={submit}>
              {busy ? "提交中…" : "提交举报"}
            </button>
            <button className="btn btn-ghost btn-sm" type="button" disabled={busy} onClick={() => setOpen(false)}>
              取消
            </button>
          </div>
        </div>
      )}
    </span>
  );
}
