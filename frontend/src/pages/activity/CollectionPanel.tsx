import { useState } from "react";
import { Link } from "react-router-dom";
import { activityApi } from "../../api/activities";
import { useSitePolicy } from "../../api/sitePolicy";
import Avatar from "../../components/Avatar";
import {
  REVIEW_STATUS_BADGE_CLASS,
  REVIEW_STATUS_LABELS,
} from "../../types/activities";
import type { ActivityPanelProps } from "./types";

export function CollectionSubmitCard({
  a, setActivity, busy, setBusy, setError,
}: ActivityPanelProps) {
  const [files, setFiles] = useState<File[]>([]);

  const doSubmit = async () => {
    if (files.length < 1) return;
    setBusy(true); setError("");
    try { setActivity(await activityApi.submit(a.id, files)); setFiles([]); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
      <h3 className="section-h">提交作品</h3>
      <div className="hint" style={{ marginBottom: 8 }}>一人一作品，提交即锁定。</div>
      <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files || []))} />
      {files.length > 0 && <div className="hint">已选 {files.length} 个文件</div>}
      <div style={{ marginTop: 8 }}>
        <button className="btn btn-primary btn-sm" onClick={doSubmit} disabled={busy || files.length < 1}>提交作品</button>
      </div>
    </div>
  );
}

export default function CollectionPanel({
  a, setActivity, user, busy, setBusy, setError, hideSubmit,
}: ActivityPanelProps & { hideSubmit?: boolean }) {
  const policy = useSitePolicy();
  const syncMb = Math.round(policy.sync_upload_max_bytes / 1024 / 1024);
  const [comments, setComments] = useState<Record<number, string>>({});
  const isOwner = !!user && a.creator?.id === user.id;
  const isReviewer = !!user && (!!user.can_review_collections || isOwner);
  const canSubmit = a.status === "collecting" && !a.my_submission && !hideSubmit;

  const doReview = async (sid: number, decision: "accepted" | "rejected") => {
    setBusy(true); setError("");
    try { setActivity(await activityApi.review(a.id, sid, decision, comments[sid] || "")); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
        <h3 className="section-h">征集规则</h3>
        <ul className="muted">
          <li>允许后缀：{a.allowed_extensions ? a.allowed_extensions : "不限（除可执行/脚本类）"}</li>
          <li>单文件大小上限：{a.max_file_size ? `${Math.round(a.max_file_size / 1024 / 1024)} MB` : `${syncMb} MB`}</li>
          <li>单作品文件数上限：{a.max_files_per_submission}</li>
          <li>最大征集数量：{a.max_submissions ?? "不限"}{a.max_submissions && a.submissions ? `（已收 ${a.submissions.length}）` : ""}</li>
        </ul>
      </div>

      {canSubmit && (
        <CollectionSubmitCard
          a={a} setActivity={setActivity} user={user}
          busy={busy} setBusy={setBusy} setError={setError}
        />
      )}

      {a.my_submission && (
        <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
          <h3 className="section-h">我的作品</h3>
          <div className="pc-meta" style={{ marginBottom: 8 }}>
            {a.review_enabled && (
              <span className={"badge " + REVIEW_STATUS_BADGE_CLASS[a.my_submission.review_status]}>{REVIEW_STATUS_LABELS[a.my_submission.review_status]}</span>
            )}
          </div>
          {a.my_submission.files.map((f) => (
            <div key={f.id}><a href={f.file_url} target="_blank" rel="noreferrer">{f.file_name}</a></div>
          ))}
          {a.my_submission.review_comment && (
            <div className="muted" style={{ marginTop: 8 }}>评语：{a.my_submission.review_comment}</div>
          )}
        </div>
      )}

      {a.submissions && a.submissions.length > 0 && (
        <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
          <h3 className="section-h">{!a.review_enabled ? "作品" : isReviewer ? "作品复审" : "录用作品"}</h3>
          {a.review_enabled && !isReviewer && <div className="hint" style={{ marginBottom: 8 }}>仅展示已录用作品。</div>}
          {a.submissions.map((s) => (
            <div key={s.id} className="detail-section" style={{ padding: "12px 0", borderBottom: "1px solid var(--c-border)" }}>
              <div className="pc-meta" style={{ marginBottom: 6 }}>
                <Link to={`/u/${s.submitter.id}`}><Avatar user={s.submitter} /></Link>
                <span>{s.submitter.nickname || s.submitter.username}</span>
                {a.review_enabled && (
                  <span className={"badge " + REVIEW_STATUS_BADGE_CLASS[s.review_status]}>{REVIEW_STATUS_LABELS[s.review_status]}</span>
                )}
              </div>
              {s.files.map((f) => (
                <div key={f.id}><a href={f.file_url} target="_blank" rel="noreferrer">{f.file_name}</a></div>
              ))}
              {s.review_comment && <div className="muted" style={{ marginTop: 4 }}>评语：{s.review_comment}</div>}
              {a.review_enabled && isReviewer && (a.status === "collecting" || a.status === "reviewing") && s.review_status === "pending" && (
                <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <input className="input" style={{ flex: 1, minWidth: 200 }} placeholder="评语（选填）" value={comments[s.id] || ""} onChange={(e) => setComments((c) => ({ ...c, [s.id]: e.target.value }))} />
                  <button className="btn btn-success btn-sm" onClick={() => doReview(s.id, "accepted")} disabled={busy}>录用</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => doReview(s.id, "rejected")} disabled={busy}>退稿</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
