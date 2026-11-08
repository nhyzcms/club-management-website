import { useState } from "react";
import { postcardAdminApi, type ReviewRow } from "../../api/postcardAdmin";
import { fmtTime, verdictSummary } from "../../components/postcard/admin/pure";
import "../../styles/postcard-review.css";

/**
 * 审核台「明信片」桌（桌面与手机共用）：双面照片 + AI 判定 + 通过/不通过。
 *
 * 说明：这是**审核台的一张桌**，不是独立页面——并入既有 `/#/reviews`，
 * 与内容送审 / 意见反馈 / 举报共用同一套队列、「下一条」与权限规则。
 */
export default function PostcardReviewPane({
  item,
  busy,
  flash,
  onDecision,
  onNext,
  onLightbox,
}: {
  item: ReviewRow;
  busy: boolean;
  flash?: string;
  onDecision: (decision: "pass" | "fail", note: string) => void;
  onNext: () => void;
  onLightbox: (url: string) => void;
}) {
  const [note, setNote] = useState("");
  const verdict = verdictSummary(item.ai_verdict);
  const stateLabel =
    item.review_state === "manual_pending" ? "待人工复核" : "AI 判定不匹配";

  return (
    <div className="pcx-pane">
      <div className="pcx-meta">
        <span className={`pcx-badge ${item.review_state === "manual_pending" ? "is-manual" : "is-failed"}`}>
          {stateLabel}
        </span>
        <span className="pcx-barcode tnum">条码 {item.barcode}</span>
        {flash && <span className="pcx-flash">{flash}</span>}
      </div>

      <h2 className="pcx-title">
        {item.registration.sender_name} · {item.registration.grade_label}
        {item.registration.class_no}班
      </h2>
      <p className="pcx-sub">
        寄达：{item.registration.dest_region} {item.registration.dest_school}
        <span className="sep">·</span>
        登记码 <span className="tnum">{item.registration.reg_code}</span>
        <span className="sep">·</span>
        {fmtTime(item.registration.created_at)}
      </p>

      {item.photo_ids.length === 0 ? (
        <p className="pcx-empty">照片已清理或已删除（通过即删 / 失败 24h 兜底）。</p>
      ) : (
        <div className="pcx-photos">
          {item.photo_ids.map((id, i) => (
            <button
              key={id}
              type="button"
              className="pcx-photo"
              aria-label={`查看第 ${i + 1} 张照片`}
              onClick={() => onLightbox(postcardAdminApi.reviewPhotoUrl(id))}
            >
              <img
                src={postcardAdminApi.reviewPhotoUrl(id)}
                alt={`${item.barcode} 第 ${i + 1} 张照片`}
                loading="lazy"
              />
            </button>
          ))}
        </div>
      )}

      {verdict && (
        <div className="pcx-verdict">
          {verdict.manual && <p className="pcx-ok">{verdict.manual}</p>}
          <p>
            AI 判定：
            {verdict.matched === null ? "（无结论）" : verdict.matched ? "匹配" : "不匹配"}
            {verdict.mismatched.length > 0 && `；不一致项：${verdict.mismatched.join("、")}`}
            {verdict.blacklist.length > 0 && `；黑名单形象：${verdict.blacklist.join("、")}`}
          </p>
          {verdict.comment && <p className="pcx-muted">说明：{verdict.comment}</p>}
        </div>
      )}

      <label className="pcx-note">
        <span>复核备注（可选，会写进审计）</span>
        <input
          value={note}
          maxLength={500}
          placeholder="例如：照片与填写一致，AI 误判"
          onChange={(e) => setNote(e.target.value)}
        />
      </label>

      <div className="pcx-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() => onDecision("pass", note)}
        >
          通过
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={busy}
          onClick={() => onDecision("fail", note)}
        >
          不通过
        </button>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={onNext}>
          下一条
        </button>
      </div>
    </div>
  );
}
