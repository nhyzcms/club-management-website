import { useCallback, useEffect, useState } from "react";
import Pagination from "../../Pagination";
import {
  postcardAdminApi,
  type AuditRow,
  type Paged,
  type SuggestionRow,
} from "../../../api/postcardAdmin";
import { errMessage, fmtTime, isForbidden } from "./pure";

/** 建议箱与审计日志（只读，各 20 条/页）。 */
export default function MiscTab() {
  const [sugPage, setSugPage] = useState(1);
  const [suggestions, setSuggestions] = useState<Paged<SuggestionRow> | null>(null);
  const [auditPage, setAuditPage] = useState(1);
  const [audit, setAudit] = useState<Paged<AuditRow> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [s, a] = await Promise.all([
        postcardAdminApi.suggestions(sugPage),
        postcardAdminApi.audit(auditPage),
      ]);
      setSuggestions(s);
      setAudit(a);
    } catch (e) {
      setError(isForbidden(e) ? "需要 manage_postcard 权限。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, [sugPage, auditPage]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !suggestions) return <p className="pa-muted">加载中…</p>;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}

      <section className="pa-card">
        <h3 className="pa-card-title">建议（{suggestions?.count ?? 0}）</h3>
        {(suggestions?.results ?? []).length === 0 ? (
          <p className="pa-muted">还没有收到建议。</p>
        ) : (
          <ul className="pa-list">
            {suggestions!.results.map((s) => (
              <li key={s.id}>
                <p>{s.content}</p>
                <p className="pa-muted">
                  {fmtTime(s.created_at)}
                  {s.contact ? ` · 联系方式：${s.contact}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
        <Pagination
          page={sugPage}
          totalPages={suggestions ? Math.max(1, Math.ceil(suggestions.count / 20)) : 1}
          onChange={setSugPage}
        />
      </section>

      <section className="pa-card">
        <h3 className="pa-card-title">审计日志（{audit?.count ?? 0}）</h3>
        {(audit?.results ?? []).length === 0 ? (
          <p className="pa-muted">还没有审计记录。</p>
        ) : (
          <ul className="pa-list pa-audit">
            {audit!.results.map((a) => (
              <li key={a.id}>
                <strong>{a.action}</strong> <span className="tnum">{a.target}</span>
                <p className="pa-muted">
                  {fmtTime(a.created_at)} · {a.user || "系统"} · {a.ip || "—"}
                  {a.detail ? ` · ${JSON.stringify(a.detail)}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
        <Pagination
          page={auditPage}
          totalPages={audit ? Math.max(1, Math.ceil(audit.count / 20)) : 1}
          onChange={setAuditPage}
        />
      </section>
    </div>
  );
}
