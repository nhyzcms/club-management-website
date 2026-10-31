import { useEffect, useState } from "react";
import { activityApi } from "../../api/activities";
import type { ActivityDetail } from "../../types/activities";
import Avatar from "../../components/Avatar";
import { useTurnstile } from "../../turnstile";
import type { ActivityPanelProps } from "./types";

export default function DeliberationPanel({
  a, setActivity, user, busy, setBusy, setError,
}: ActivityPanelProps) {
  const [selected, setSelected] = useState<number[]>(a.my_selections ?? []);
  const total = a.total_ballots ?? 0;
  const canVote = a.status === "open" && a.my_selections === null;
  const options = a.options ?? [];
  // 游客投票在启用 Turnstile 时逐票校验；成员按账号判重，不需要。
  const {
    containerRef: turnstileRef, token: turnstileToken, reset: resetTurnstile,
    enabled: turnstileEnabled,
  } = useTurnstile(!user);
  const needTurnstile = canVote && turnstileEnabled && !turnstileToken;

  useEffect(() => {
    setSelected(a.my_selections ?? []);
  }, [a.my_selections]);

  const toggleOption = (oid: number) => {
    setSelected((cur) => {
      if (cur.includes(oid)) return cur.filter((x) => x !== oid);
      if (a.max_choices_per_voter === 1) return [oid];
      if (cur.length >= a.max_choices_per_voter) return cur;
      return [...cur, oid];
    });
  };

  const doVote = async () => {
    if (selected.length < 1 || needTurnstile) return;
    setBusy(true); setError("");
    try { setActivity(await activityApi.vote(a.id, selected, turnstileToken || undefined)); }
    catch (e: unknown) {
      if (turnstileEnabled) resetTurnstile();
      setError(e instanceof Error ? e.message : String(e));
    }
    finally { setBusy(false); }
  };

  return (
    <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
      <h3 className="section-h">投票</h3>
      {canVote ? (
        <>
          <div className="hint" style={{ marginBottom: 8 }}>
            可选 {a.max_choices_per_voter} 项（{a.max_choices_per_voter === 1 ? "一人一票" : "一人多票"}）；一经投出不可更改。
          </div>
          {options.map((o) => {
            const on = selected.includes(o.id);
            return (
              <label key={o.id} className={"vote-opt" + (on ? " is-on" : "")}>
                <input
                  type={a.max_choices_per_voter === 1 ? "radio" : "checkbox"}
                  name="vote"
                  checked={on}
                  onChange={() => toggleOption(o.id)}
                />
                <span className="vote-opt-text">{o.text}</span>
              </label>
            );
          })}
          {turnstileEnabled && <div ref={turnstileRef} style={{ margin: "8px 0" }} />}
          <button className="btn btn-primary btn-sm" onClick={doVote} disabled={busy || selected.length < 1 || needTurnstile}>投票</button>
        </>
      ) : (
        <>
          {a.my_selections !== null && (
            <div className="hint" style={{ marginBottom: 8 }}>
              你投了：{a.my_selections.map((oid) => options.find((o) => o.id === oid)?.text).filter(Boolean).join("、")}
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            {options.map((o) => {
              const pct = total > 0 ? Math.round((o.vote_count / total) * 100) : 0;
              return (
                <div key={o.id} style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>{o.text}</span>
                    <span className="muted">{o.vote_count} 票 · {pct}%</span>
                  </div>
                  <div style={{ height: 8, background: "#e5e7eb", borderRadius: 4, overflow: "hidden", marginTop: 4 }}>
                    <div style={{ width: `${pct}%`, height: "100%", background: "#2563eb" }} />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="muted" style={{ marginTop: 8 }}>共 {total} 人投票</div>
          <BallotDetails a={a} />
        </>
      )}
    </div>
  );
}

function BallotDetails({ a }: { a: ActivityDetail }) {
  const options = a.options ?? [];
  if (a.ballots === null) {
    return (
      <div className="alert alert-info" style={{ marginTop: 12 }}>
        <span>秘密投票 —— 个人投票明细不公开。</span>
      </div>
    );
  }
  if (a.ballots.length === 0) return null;
  return (
    <details style={{ marginTop: 12 }}>
      <summary className="muted">查看投票明细（{a.ballots.length}）</summary>
      <ul style={{ marginTop: 8 }}>
        {a.ballots.map((b) => (
          <li key={b.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
            {b.voter ? (
              <>
                <Avatar user={b.voter} />
                <span>{b.voter.nickname || b.voter.username}</span>
              </>
            ) : (
              <>
                <span className="avatar avatar--sm" style={{ background: "#d1d5db" }} aria-hidden="true" />
                <span className="muted">游客</span>
              </>
            )}
            <span className="muted">投：{b.option_ids.map((oid) => options.find((o) => o.id === oid)?.text).filter(Boolean).join("、")}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
