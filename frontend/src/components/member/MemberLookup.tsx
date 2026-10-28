import { useEffect, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api/client";
import MemberResultCard, { type MemberPublicResult } from "./MemberResultCard";
import "../../styles/member.css";

/** 后端 accounts/member_lookup.py 的额度快照：limit=null 表示不限。 */
export interface MemberLookupQuota {
  limit: number | null;
  used: number;
  remaining: number | null;
  reset_at: string | null;
  window_hours: number;
}

const ICON_SEARCH = (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="7" />
    <path d="M21 21l-4-4" />
  </svg>
);

function quotaHint(quota: MemberLookupQuota | null): string {
  if (!quota) return "按真实姓名或社员编号（识别码）精确查询。";
  if (quota.limit === null) return "你当前查询次数不限。";
  const remaining = quota.remaining ?? 0;
  return `每 ${quota.window_hours} 小时可查 ${quota.limit} 次，今日还可查 ${remaining} 次。`;
}

/**
 * 「社员查询」（首页社团概览）：按真实姓名 / 社员编号查社员，
 * 结果卡与扫码校验页同组件同字段；额度按查询者身份分档（服务端判定）。
 */
export default function MemberLookup() {
  const [q, setQ] = useState("");
  const [quota, setQuota] = useState<MemberLookupQuota | null>(null);
  const [results, setResults] = useState<MemberPublicResult[] | null>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const loadQuota = () => {
    api.memberLookupQuota()
      .then((d: any) => setQuota((d?.quota ?? null) as MemberLookupQuota | null))
      .catch(() => {});
  };

  useEffect(loadQuota, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const value = q.trim();
    if (!value || busy) return;
    setBusy(true);
    setErr("");
    try {
      const data: any = await api.memberLookup(value);
      setResults((data?.results ?? []) as MemberPublicResult[]);
      setQuota((data?.quota ?? null) as MemberLookupQuota | null);
      setOpen(true);
    } catch (ex: any) {
      // 429（额度用尽）/ 400（空输入）都会带服务端中文原因，直接展示
      setErr(ex?.message || "查询失败，请稍后重试。");
      loadQuota();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="member-lookup">
      <div className="member-lookup-title">
        <span className="bar" />
        社员查询
      </div>
      <form className="member-lookup-form" onSubmit={submit}>
        <input
          className="input"
          type="search"
          value={q}
          maxLength={100}
          onChange={(e) => setQ(e.target.value)}
          placeholder="真实姓名 / 社员编号"
          aria-label="社员查询"
        />
        <button className="btn btn-primary btn-sm" type="submit" disabled={busy || !q.trim()}>
          {ICON_SEARCH}
          <span>{busy ? "查询中…" : "查询"}</span>
        </button>
      </form>
      <p className="member-lookup-hint">{quotaHint(quota)}</p>
      {err && <p className="member-claim-err" role="alert">{err}</p>}

      {open && createPortal(
        <div
          className="modal-scrim is-open"
          role="dialog"
          aria-modal="true"
          aria-label="社员查询结果"
          style={{ zIndex: 10000 }}
          onClick={() => setOpen(false)}
        >
          <div className="modal" style={{ maxWidth: 420 }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h3>社员查询结果</h3>
                <p>{quotaHint(quota)}</p>
              </div>
              <button
                type="button"
                className="modal-close"
                aria-label="关闭"
                onClick={() => setOpen(false)}
              >
                ×
              </button>
            </div>
            <div className="modal-body center">
              {results && results.length > 0 ? (
                results.map((r) => (
                  <div className="member-lookup-result" key={r.code}>
                    <MemberResultCard result={r} note="本页来自社员查询，仅展示公开信息。" />
                  </div>
                ))
              ) : (
                <p className="muted">
                  未找到匹配的社员——请确认姓名与社员编号是否完整、准确。
                </p>
              )}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
