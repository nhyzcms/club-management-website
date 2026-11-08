import { useCallback, useEffect, useState } from "react";
import Pagination from "../../Pagination";
import { postcardAdminApi, type Paged, type ReviewRow } from "../../../api/postcardAdmin";
import { errMessage, fmtTime, isForbidden, verdictSummary } from "./pure";

/**
 * 人工复核台：AI 转人工（manual_pending）与 AI 判不匹配（ai_failed）两张队列。
 * 通过 → 照片立即删除；不通过 → 24h TTL 兜底删除。判定全量进审计。
 */
export default function ReviewTab() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<ReviewRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await postcardAdminApi.reviewQueue(page));
    } catch (e) {
      setError(isForbidden(e) ? "需要 review_postcard 权限才能复核。" : errMessage(e));
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (itemId: number, decision: "pass" | "fail") => {
    setError("");
    setNotice("");
    setBusyId(itemId);
    try {
      const r = await postcardAdminApi.reviewDecision(itemId, decision, notes[itemId] || "");
      setNotice(`条码已判定：${r.review_label}`);
      await load();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusyId(null);
    }
  };

  if (loading && !data) return <p className="pa-muted">加载中…</p>;

  const rows = data?.results ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.count / 20)) : 1;

  return (
    <div className="pa-stack">
      {error && <p className="pa-error">{error}</p>}
      {notice && <p className="pa-ok">{notice}</p>}
      {rows.length === 0 ? (
        <p className="pa-muted">当前没有待复核的明信片。</p>
      ) : (
        <div className="pa-review-list">
          {rows.map((row) => {
            const v = verdictSummary(row.ai_verdict);
            return (
              <article key={row.item_id} className="pa-card pa-review">
                <header className="pa-review-head">
                  <span className="pa-badge tnum">{row.barcode}</span>
                  <span>
                    {row.registration.sender_name} · {row.registration.grade_label}
                    {row.registration.class_no}班
                  </span>
                  <span className="pa-muted">
                    {row.registration.dest_region} {row.registration.dest_school}
                  </span>
                  <span className="pa-muted">{fmtTime(row.registration.created_at)}</span>
                </header>

                <div className="pa-photos">
                  {row.photo_ids.length === 0 && <p className="pa-muted">照片已清理或被删除。</p>}
                  {row.photo_ids.map((id, i) => (
                    <a
                      key={id}
                      href={postcardAdminApi.reviewPhotoUrl(id)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src={postcardAdminApi.reviewPhotoUrl(id)}
                        alt={`${row.barcode} 第 ${i + 1} 张照片`}
                        loading="lazy"
                      />
                    </a>
                  ))}
                </div>

                {v && (
                  <div className="pa-verdict">
                    {v.manual && <p className="pa-ok">{v.manual}</p>}
                    <p>
                      AI 判定：
                      {v.matched === null ? "（无结论）" : v.matched ? "匹配" : "不匹配"}
                      {v.mismatched.length > 0 && `；不一致项：${v.mismatched.join("、")}`}
                      {v.blacklist.length > 0 && `；黑名单形象：${v.blacklist.join("、")}`}
                    </p>
                    {v.comment && <p className="pa-muted">说明：{v.comment}</p>}
                  </div>
                )}

                <div className="pa-review-actions">
                  <input
                    placeholder="复核备注（可选，会写进审计）"
                    value={notes[row.item_id] || ""}
                    maxLength={500}
                    onChange={(e) => setNotes((prev) => ({ ...prev, [row.item_id]: e.target.value }))}
                  />
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={busyId === row.item_id}
                    onClick={() => void decide(row.item_id, "pass")}
                  >
                    通过
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={busyId === row.item_id}
                    onClick={() => void decide(row.item_id, "fail")}
                  >
                    不通过
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </div>
  );
}
