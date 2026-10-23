import { useState } from "react";
import { api } from "../../api/client";
import type { MemberIdentityCandidate } from "../../types/member";
import "../../styles/member.css";

/**
 * 认领表单（Part A / ADR-0025）：从候选身份中选一条 + 手机号后四位 → 绑定。
 *
 * 注册后的认领阶段与个人页「社员身份」面板共用同一组件，避免两处漂移。
 * 服务端强制「账号真实姓名 == 名册行姓名」，前端列表仅作展示。
 */
export default function MemberClaimForm({
  candidates,
  onDone,
}: {
  candidates: MemberIdentityCandidate[];
  onDone: () => void;
}) {
  const [picked, setPicked] = useState<number | null>(candidates.length === 1 ? candidates[0].id : null);
  const [last4, setLast4] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const canSubmit = picked !== null && last4.length === 4 && !busy;

  const submit = () => {
    if (picked === null || !canSubmit) return;
    setBusy(true);
    setErr("");
    api.memberClaim(picked, last4)
      .then(() => onDone())
      .catch((e: any) => setErr(e.message || "认领失败，请稍后重试。"))
      .finally(() => setBusy(false));
  };

  return (
    <div className="member-claim">
      <div className="member-claim-list" role="radiogroup" aria-label="候选身份">
        {candidates.map((c) => (
          <label
            key={c.id}
            className={"member-claim-item" + (picked === c.id ? " is-picked" : "")}
          >
            <input
              type="radio"
              name="member-identity"
              value={c.id}
              checked={picked === c.id}
              onChange={() => setPicked(c.id)}
            />
            <span className="member-claim-name">{c.name}</span>
            <span className="muted">
              第 {c.cohort} 届
            </span>
          </label>
        ))}
      </div>
      <div className="field">
        <label className="label" htmlFor="member-phone-last4">
          手机号后四位
        </label>
        <input
          id="member-phone-last4"
          className="input"
          inputMode="numeric"
          autoComplete="off"
          maxLength={4}
          value={last4}
          disabled={busy}
          onChange={(e) => setLast4(e.target.value.replace(/\D/g, "").slice(0, 4))}
          placeholder="名册中登记的手机号后四位"
        />
      </div>
      {err && (
        <p className="member-claim-err" role="alert">
          {err}
        </p>
      )}
      <button className="btn btn-primary btn-block" type="button" disabled={!canSubmit} onClick={submit}>
        {busy ? "绑定中…" : "确认绑定"}
      </button>
    </div>
  );
}
