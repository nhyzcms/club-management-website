import { useState, type FormEvent } from "react";
import { messagingApi } from "../../api/messaging";
import "../../styles/form.css";

export default function MuteUserPanel({ userId }: { userId: number }) {
  const [reason, setReason] = useState("");
  const [permanent, setPermanent] = useState(true);
  const [endsLocal, setEndsLocal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const mute = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setNote("");
    setBusy(true);
    try {
      let ends_at: string | null = null;
      if (!permanent) {
        if (!endsLocal) {
          setError("请填写结束时间，或勾选永久。");
          setBusy(false);
          return;
        }
        const d = new Date(endsLocal);
        if (Number.isNaN(d.getTime()) || d.getTime() <= Date.now()) {
          setError("结束时间须晚于当前时间。");
          setBusy(false);
          return;
        }
        ends_at = d.toISOString();
      }
      await messagingApi.muteUser(userId, { reason: reason.trim(), ends_at });
      setNote("已全站禁言。对方不能发评论或私信，仍可登录、阅读、接收。");
    } catch (err: any) {
      setError(err?.message || "禁言失败");
    } finally {
      setBusy(false);
    }
  };

  const lift = async () => {
    setError("");
    setNote("");
    setBusy(true);
    try {
      await messagingApi.liftMute(userId);
      setNote("已解除全站禁言。");
    } catch (err: any) {
      setError(err?.message || "解除失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card card-pad form-stack" onSubmit={mute} style={{ marginBottom: "var(--s-4)" }}>
      <h2 className="profile-panel-title">全站禁言</h2>
      <p className="muted" style={{ marginTop: "-8px" }}>
        禁止其发评论、发私信；不影响登录与阅读。不是关掉某条内容的评论区。
      </p>
      {note && <div className="alert alert-success" role="status"><span>{note}</span></div>}
      {error && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}
      <div className="field">
        <label className="label" htmlFor="mu-reason">理由</label>
        <textarea
          className="textarea"
          id="mu-reason"
          name="reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          maxLength={500}
          placeholder="可选，会写入纪律通知"
        />
      </div>
      <label className="check">
        <input type="checkbox" checked={permanent} onChange={(e) => setPermanent(e.target.checked)} />
        永久
      </label>
      {!permanent && (
        <div className="field">
          <label className="label" htmlFor="mu-ends">结束时间</label>
          <input
            className="input"
            id="mu-ends"
            name="ends-at"
            type="datetime-local"
            value={endsLocal}
            onChange={(e) => setEndsLocal(e.target.value)}
          />
        </div>
      )}
      <div className="form-actions">
        <button className="btn btn-ghost" type="button" onClick={lift} disabled={busy}>解除禁言</button>
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "处理中…" : "全站禁言"}</button>
      </div>
    </form>
  );
}
