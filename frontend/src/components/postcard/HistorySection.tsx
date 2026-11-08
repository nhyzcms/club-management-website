import { useState } from "react";
import type { PostcardPortal, PostcardRegistrationSummary } from "../../api/postcard";
import { postcardApi } from "../../api/postcard";
import { hasAiFailedItem, schoolsInRegion } from "./pure";

interface Props {
  regs: PostcardRegistrationSummary[];
  portal: PostcardPortal;
  fingerprint: string;
  isMobile: boolean;
  onChanged: () => void;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const STATUS_BADGE_CLASS: Record<string, string> = {
  registered: "pc-badge pc-badge-ok",
  reported: "pc-badge pc-badge-info",
  cancelled: "pc-badge pc-badge-muted",
};

const REVIEW_BADGE_CLASS: Record<string, string> = {
  pending: "pc-badge pc-badge-info",
  ai_passed: "pc-badge pc-badge-ok",
  ai_failed: "pc-badge pc-badge-bad",
  manual_pending: "pc-badge pc-badge-info",
  manual_passed: "pc-badge pc-badge-ok",
  manual_failed: "pc-badge pc-badge-bad",
};

/** 审核通过的照片服务端已删（404），这些状态才尝试加载。 */
const PHOTO_VISIBLE_STATES = new Set([
  "pending", "ai_failed", "manual_pending", "manual_failed",
]);

/**
 * 历史登记记录：三轨归属自动带出本人的登记单；查看 / 修改寄出人信息 /
 * 取消 / 申请人工复核。登记码即能力凭证，展示时突出提醒保存。
 */
export default function HistorySection({ regs, portal, fingerprint, isMobile, onChanged }: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  const [confirmingCancel, setConfirmingCancel] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [hiddenPhotos, setHiddenPhotos] = useState<Set<number>>(new Set());
  // 整批取消（同一登记码下全部提交，不可逆）：需重新输入 6 位码才可提交。
  const [batchCode, setBatchCode] = useState<string | null>(null);
  const [batchInput, setBatchInput] = useState("");

  // 修改表单草稿（按提交存）
  const [draft, setDraft] = useState({
    sender_name: "", grade: "", class_no: "", dest_region: "", dest_school: "",
  });

  const ghostBtn = isMobile ? "m-btn-ghost" : "btn btn-ghost btn-sm";
  const primaryBtn = isMobile ? "m-btn-primary" : "btn btn-primary btn-sm";
  const dangerBtn = isMobile ? "m-btn-ghost" : "btn btn-ghost btn-sm";

  const startEdit = (reg: PostcardRegistrationSummary) => {
    setEditing(reg.id);
    setNotice("");
    setDraft({
      sender_name: reg.sender_name,
      grade: reg.grade,
      class_no: String(reg.class_no),
      dest_region: reg.dest_region,
      dest_school: reg.dest_school,
    });
  };

  const saveEdit = async (reg: PostcardRegistrationSummary) => {
    if (busyId) return;
    if (!draft.sender_name.trim()) {
      setNotice("姓名不能为空");
      return;
    }
    setBusyId(reg.id);
    setNotice("");
    try {
      await postcardApi.update(reg.reg_code, {
        sender_name: draft.sender_name.trim(),
        grade: draft.grade,
        class_no: Number(draft.class_no),
        dest_region: draft.dest_region,
        dest_school: draft.dest_school,
      }, fingerprint, reg.id);
      setEditing(null);
      onChanged();
    } catch (err: any) {
      setNotice(err?.message || "保存失败，请稍后重试。");
    } finally {
      setBusyId(null);
    }
  };

  /** 取消单份提交（不可逆，卡片内二次确认）。 */
  const cancelReg = async (reg: PostcardRegistrationSummary) => {
    if (busyId) return;
    setBusyId(reg.id);
    setNotice("");
    try {
      await postcardApi.cancel(reg.reg_code, fingerprint, "one", reg.id);
      setConfirmingCancel(null);
      onChanged();
    } catch (err: any) {
      setNotice(err?.message || "取消失败，请稍后重试。");
    } finally {
      setBusyId(null);
    }
  };

  /** 整批取消：同一登记码下的全部提交（不可逆，需重新输入 6 位码）。 */
  const cancelBatch = async (regCode: string) => {
    if (busyId) return;
    if (batchInput.trim() !== regCode) {
      setNotice("输入的登记码不一致，未执行整批取消。");
      return;
    }
    setBusyId(-1);
    setNotice("");
    try {
      const d = await postcardApi.cancel(regCode, fingerprint, "all");
      const n = (d as any).cancelled_count ?? 1;
      setNotice(`已取消该登记码下的 ${n} 份提交。`);
      setBatchCode(null);
      setBatchInput("");
      onChanged();
    } catch (err: any) {
      setNotice(err?.message || "整批取消失败，请稍后重试。");
    } finally {
      setBusyId(null);
    }
  };

  const requestReview = async (reg: PostcardRegistrationSummary) => {
    if (busyId) return;
    setBusyId(reg.id);
    setNotice("");
    try {
      // 已发码走 6 位码；未发码（AI 判不匹配）用登记的轮询凭证。
      const d = reg.code_granted
        ? await postcardApi.requestReview(reg.reg_code, fingerprint)
        : await postcardApi.requestReviewByToken(reg.access_token || "");
      setNotice(d.message);
      onChanged();
    } catch (err: any) {
      setNotice(err?.message || "提交复核失败，请稍后重试。");
    } finally {
      setBusyId(null);
    }
  };

  const hidePhoto = (id: number) => {
    setHiddenPhotos((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  if (regs.length === 0) {
    return (
      <div className="pc-history">
        <p className="muted">
          还没有登记记录。登记提交后，这里会显示你的全部明信片（同一设备的记录自动归集）。
        </p>
      </div>
    );
  }

  const schoolOptions = schoolsInRegion(portal.schools, draft.dest_region);

  return (
    <div className="pc-history">
      {notice && <p className="pc-history-notice">{notice}</p>}
      {regs.map((reg) => {
        const isEditing = editing === reg.id;
        const isCancelling = confirmingCancel === reg.id;
        const isBusy = busyId === reg.id;
        // 未发码（审核未通过）时只读：能力凭证还没发放，不给改/取消入口。
        const canModify = reg.status !== "cancelled" && reg.code_granted;
        const batchCount = regs.filter((r) => r.reg_code === reg.reg_code).length;
        return (
          <article key={reg.id} className={"pc-reg" + (reg.status === "cancelled" ? " is-cancelled" : "")}>
            <header className="pc-reg-head">
              <div className="pc-reg-code-wrap">
                <span className="pc-reg-code-label">登记码</span>
                <span className="pc-reg-code tnum">{reg.reg_code}</span>
                {!reg.code_granted && (
                  <span className="pc-reg-code-hint">审核通过后发放</span>
                )}
              </div>
              <span className={STATUS_BADGE_CLASS[reg.status] || "pc-badge"}>{reg.status_label}</span>
            </header>

            {isEditing ? (
              <div className="pc-reg-edit">
                <div className="pc-field-grid">
                  <div className="pc-field">
                    <label className="label">姓名</label>
                    <input
                      className="input"
                      value={draft.sender_name}
                      maxLength={64}
                      onChange={(e) => setDraft({ ...draft, sender_name: e.target.value })}
                    />
                  </div>
                  <div className="pc-field">
                    <label className="label">年级</label>
                    <select
                      className="input"
                      value={draft.grade}
                      onChange={(e) => setDraft({ ...draft, grade: e.target.value })}
                    >
                      {portal.grades.map((g) => (
                        <option key={g.value} value={g.value}>{g.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="pc-field">
                    <label className="label">班级</label>
                    <select
                      className="input"
                      value={draft.class_no}
                      onChange={(e) => setDraft({ ...draft, class_no: e.target.value })}
                    >
                      {portal.classes.map((c) => (
                        <option key={c} value={String(c)}>{c} 班</option>
                      ))}
                    </select>
                  </div>
                  <div className="pc-field">
                    <label className="label">寄达区</label>
                    <select
                      className="input"
                      value={draft.dest_region}
                      onChange={(e) => setDraft({
                        ...draft,
                        dest_region: e.target.value,
                        dest_school: "",
                      })}
                    >
                      {portal.regions.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </div>
                  <div className="pc-field">
                    <label className="label">寄达校</label>
                    <select
                      className="input"
                      value={draft.dest_school}
                      disabled={!draft.dest_region}
                      onChange={(e) => setDraft({ ...draft, dest_school: e.target.value })}
                    >
                      <option value="">请选择</option>
                      {schoolOptions.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="pc-reg-actions">
                  <button type="button" className={primaryBtn} disabled={isBusy} onClick={() => void saveEdit(reg)}>
                    {isBusy ? "保存中…" : "保存修改"}
                  </button>
                  <button type="button" className={ghostBtn} onClick={() => setEditing(null)}>
                    取消编辑
                  </button>
                </div>
                <p className="muted" style={{ fontSize: 12 }}>
                  条码与照片对应实物明信片，登记后不可修改；如填错了条码，请取消本单后重新登记。
                </p>
              </div>
            ) : (
              <>
                <p className="pc-reg-meta">
                  {reg.sender_name} · {reg.grade_label} {reg.class_no} 班 → {reg.dest_region} {reg.dest_school}
                  <span className="pc-reg-time">登记于 {fmtTime(reg.created_at)}</span>
                </p>
                <ul className="pc-reg-items">
                  {reg.items.map((it) => (
                    <li key={it.id} className="pc-reg-item">
                      <div className="pc-reg-item-line">
                        <span className="tnum">条码 {it.barcode}</span>
                        <span className={STATUS_BADGE_CLASS[it.status] || "pc-badge"}>{it.status_label}</span>
                        {it.review_label && (
                          <span className={REVIEW_BADGE_CLASS[it.review_state || ""] || "pc-badge"}>
                            {it.review_label}
                          </span>
                        )}
                      </div>
                      {it.mismatched.length > 0 && (
                        <p className="pc-reg-item-mismatch">
                          AI 判定以下填写与照片不符：{it.mismatched.join("、")}
                          {it.comment ? `（${it.comment}）` : ""}
                          。如确认自己填写无误，可申请人工复核。
                        </p>
                      )}
                      {it.photos.length > 0 && PHOTO_VISIBLE_STATES.has(it.review_state || "") && (
                        <div className="pc-reg-item-photos">
                          {it.photos.map((p) =>
                            hiddenPhotos.has(p.id) ? null : (
                              <img
                                key={p.id}
                                src={postcardApi.photoUrl(p.id, reg.reg_code, fingerprint)}
                                alt={`${it.barcode} ${p.side === "front" ? "正面" : "反面"}照片`}
                                loading="lazy"
                                onError={() => hidePhoto(p.id)}
                              />
                            ),
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
                {(canModify || hasAiFailedItem(reg)) && (
                  <div className="pc-reg-actions">
                    {canModify && (
                      <button type="button" className={ghostBtn} onClick={() => startEdit(reg)}>
                        修改
                      </button>
                    )}
                    {hasAiFailedItem(reg) && (
                      <button
                        type="button"
                        className={primaryBtn}
                        disabled={isBusy}
                        onClick={() => void requestReview(reg)}
                      >
                        {isBusy ? "提交中…" : "申请人工复核"}
                      </button>
                    )}
                    {canModify && (isCancelling ? (
                      <>
                        <button type="button" className={dangerBtn} disabled={isBusy} onClick={() => void cancelReg(reg)}>
                          {isBusy ? "取消中…" : "确认取消本份（不可恢复）"}
                        </button>
                        <button type="button" className={ghostBtn} onClick={() => setConfirmingCancel(null)}>
                          返回
                        </button>
                      </>
                    ) : (
                      <button type="button" className={dangerBtn} onClick={() => setConfirmingCancel(reg.id)}>
                        取消本份
                      </button>
                    ))}
                    {canModify && batchCount > 1 && (
                      <button type="button" className={dangerBtn} onClick={() => { setBatchCode(reg.reg_code); setBatchInput(""); }}>
                        取消整批（{batchCount} 份）
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </article>
        );
      })}
      {batchCode && (
        <div className="pc-batch-cancel" role="alertdialog" aria-label="整批取消确认">
          <p>
            将取消登记码 <strong className="tnum">{batchCode}</strong> 下的全部提交，且不可恢复。
            请输入该登记码确认：
          </p>
          <div className="pc-inline">
            <input
              className="input tnum"
              inputMode="numeric"
              maxLength={6}
              value={batchInput}
              onChange={(e) => setBatchInput(e.target.value.replace(/\D/g, "").slice(0, 6))}
              aria-label="输入登记码确认整批取消"
            />
            <button
              type="button"
              className={dangerBtn}
              disabled={busyId !== null || batchInput.trim() !== batchCode}
              onClick={() => void cancelBatch(batchCode)}
            >
              确认整批取消
            </button>
            <button type="button" className={ghostBtn} onClick={() => { setBatchCode(null); setBatchInput(""); }}>
              返回
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
