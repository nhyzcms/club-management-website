import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { identityReviewsApi } from "../api/identityReviews";
import { passwordResetApi } from "../api/passwordReset";
import { reviewsApi } from "../api/reviews";
import { feedbackApi } from "../api/feedback";
import { reportsApi } from "../api/reports";
import MobilePage from "../components/MobilePage";
import ReviewPreview from "./review/ReviewPreview";
import PasswordResetPane from "./review/PasswordResetPane";
import {
  CONTENT_KINDS,
  deskTabs,
  firstContent,
  firstFeedback,
  firstIdentity,
  firstPasswordReset,
  firstReport,
  type DeskKind,
} from "../utils/reviewDesk";
import type {
  PasswordResetRequestItem,
  PasswordResetStatus,
} from "../types/passwordReset";
import {
  IDENTITY_LABELS,
  IDENTITY_STATUS_BADGE,
  IDENTITY_STATUS_LABELS,
  type IdentityReviewItem,
  type IdentityReviewStatus,
} from "../types/identityReviews";
import type { ReviewItem, ReviewStatus } from "../types/reviews";
import {
  FEEDBACK_CATEGORY_LABELS,
  FEEDBACK_STATUS_BADGE,
  FEEDBACK_STATUS_LABELS,
  type FeedbackDetail,
  type FeedbackStatus,
} from "../types/feedback";
import {
  REPORT_STATUS_BADGE,
  REPORT_STATUS_LABELS,
  REPORT_TARGET_LABELS,
  type ReportCase,
  type ReportStatus,
} from "../types/reports";
import "../styles/list.css";
import "../styles/detail.css";
import "../styles/form.css";
import "../styles/mobile-work.css";

/**
 * 手机版审核台（/#/m/review）。
 *
 * 与桌面 /#/reviews 共享同一套取数规则（utils/reviewDesk.ts）与内容预览组件
 * （ReviewPreview），保证两边看到的队列与判定完全一致；差异只在布局：
 * 竖屏单列、筛选 chip 横向滑动、操作按钮通栏，处理后自动进入下一条。
 */

const ADVANCE_MS = 900;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function MobileReviewPage() {
  const gen = useRef(0);
  // 本轮已浏览 / 已处理的条目： 「下一条」与处理动作后前进都跳过它们
  const visitedRef = useRef<Set<number>>(new Set());

  const [canContent, setCanContent] = useState(false);
  const [canIdentity, setCanIdentity] = useState(false);
  const [canFeedback, setCanFeedback] = useState(false);
  const [canReports, setCanReports] = useState(false);
  const [canPasswordReset, setCanPasswordReset] = useState(false);
  const [denied, setDenied] = useState(false);
  const [booting, setBooting] = useState(true);

  const [kind, setKind] = useState<DeskKind | null>(null);
  const [identityStatus, setIdentityStatus] = useState<IdentityReviewStatus>("pending");
  const [contentStatus, setContentStatus] = useState<ReviewStatus | "">("pending");
  const [feedbackStatus, setFeedbackStatus] = useState<FeedbackStatus | "">("pending");
  const [reportStatus, setReportStatus] = useState<ReportStatus | "">("open");
  const [passwordResetStatus, setPasswordResetStatus] = useState<PasswordResetStatus>("pending");

  const [identityItem, setIdentityItem] = useState<IdentityReviewItem | null>(null);
  const [contentRow, setContentRow] = useState<ReviewItem | null>(null);
  const [feedbackItem, setFeedbackItem] = useState<FeedbackDetail | null>(null);
  const [reportItem, setReportItem] = useState<ReportCase | null>(null);
  const [passwordResetItem, setPasswordResetItem] = useState<PasswordResetRequestItem | null>(null);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lightboxUrl, setLightboxUrl] = useState("");
  const [flash, setFlash] = useState("");
  const [closeNote, setCloseNote] = useState("");
  const [dismissNote, setDismissNote] = useState("");
  const [upholdNote, setUpholdNote] = useState("");
  const [mutePermanent, setMutePermanent] = useState(true);
  const [muteEnds, setMuteEnds] = useState("");

  const loadPane = useCallback(
    async (
      nextKind: DeskKind,
      idStatus: IdentityReviewStatus,
      cStatus: ReviewStatus | "",
      fStatus: FeedbackStatus | "",
      rStatus: ReportStatus | "",
      prStatus: PasswordResetStatus,
      excludeId?: number,
      token?: number,
    ): Promise<"ok" | "empty" | "error"> => {
      setLoading(true);
      setError("");
      setLightboxUrl("");
      const skip = visitedRef.current;
      try {
        if (nextKind === "identity") {
          const item = await firstIdentity(idStatus, excludeId, skip);
          if (token != null && token !== gen.current) return "ok";
          setIdentityItem(item);
          setContentRow(null);
          setFeedbackItem(null);
          setReportItem(null);
          setPasswordResetItem(null);
          return item ? "ok" : "empty";
        }
        if (nextKind === "passwordReset") {
          const item = await firstPasswordReset(prStatus, excludeId, skip);
          if (token != null && token !== gen.current) return "ok";
          setIdentityItem(null);
          setContentRow(null);
          setFeedbackItem(null);
          setReportItem(null);
          setPasswordResetItem(item);
          return item ? "ok" : "empty";
        }
        if (nextKind === "feedback") {
          const row = await firstFeedback(fStatus, excludeId, skip);
          const detail = row ? await feedbackApi.get(row.id) : null;
          if (token != null && token !== gen.current) return "ok";
          setIdentityItem(null);
          setContentRow(null);
          setFeedbackItem(detail);
          setReportItem(null);
          setPasswordResetItem(null);
          return row ? "ok" : "empty";
        }
        if (nextKind === "reports") {
          const row = await firstReport(rStatus, excludeId, skip);
          if (token != null && token !== gen.current) return "ok";
          setIdentityItem(null);
          setContentRow(null);
          setFeedbackItem(null);
          setReportItem(row);
          setPasswordResetItem(null);
          return row ? "ok" : "empty";
        }
        const row = await firstContent(nextKind, cStatus, excludeId, skip);
        if (token != null && token !== gen.current) return "ok";
        setIdentityItem(null);
        setContentRow(row);
        setFeedbackItem(null);
        setReportItem(null);
        setPasswordResetItem(null);
        return row ? "ok" : "empty";
      } catch (e: any) {
        if (token != null && token !== gen.current) return "ok";
        setError(e?.message || "加载失败");
        setIdentityItem(null);
        setContentRow(null);
        setFeedbackItem(null);
        setReportItem(null);
        setPasswordResetItem(null);
        return "error";
      } finally {
        if (token == null || token === gen.current) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then(async (d: any) => {
        const content = !!d.user?.permissions?.can_review_content;
        const identity = !!d.user?.permissions?.can_review_identity;
        const feedback = !!d.user?.permissions?.can_view_feedback;
        const reports = !!d.user?.permissions?.can_handle_reports;
        const passwordReset = !!d.user?.permissions?.can_review_password_reset;
        if (cancelled) return;
        setCanContent(content);
        setCanIdentity(identity);
        setCanFeedback(feedback);
        setCanReports(reports);
        setCanPasswordReset(passwordReset);
        if (!content && !identity && !feedback && !reports && !passwordReset) {
          setDenied(true);
          setBooting(false);
          return;
        }
        const order: DeskKind[] = [];
        if (identity) order.push("identity");
        if (passwordReset) order.push("passwordReset");
        if (content) order.push(...CONTENT_KINDS);
        if (feedback) order.push("feedback");
        if (reports) order.push("reports");
        // 打开页面时落到「第一个有活」的桌，而不是固定身份桌
        const probes = await Promise.all(
          order.map(async (k) => {
            try {
              if (k === "identity") return { k, hit: await firstIdentity("pending") };
              if (k === "passwordReset") return { k, hit: await firstPasswordReset("pending") };
              if (k === "feedback") return { k, hit: await firstFeedback("pending") };
              if (k === "reports") return { k, hit: await firstReport("open") };
              return { k, hit: await firstContent(k, "pending") };
            } catch {
              return { k, hit: null };
            }
          }),
        );
        if (cancelled) return;
        setKind(probes.find((p) => p.hit)?.k ?? order[0]);
        setBooting(false);
      })
      .catch(() => {
        if (!cancelled) {
          setDenied(true);
          setBooting(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (booting || !kind) return;
    const token = ++gen.current;
    visitedRef.current = new Set();
    setFlash("");
    loadPane(
      kind, identityStatus, contentStatus, feedbackStatus, reportStatus,
      passwordResetStatus, undefined, token,
    );
  }, [
    booting, kind, identityStatus, contentStatus, feedbackStatus, reportStatus,
    passwordResetStatus, loadPane,
  ]);

  useEffect(() => {
    if (!lightboxUrl) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightboxUrl("");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightboxUrl]);

  const pickKind = (next: DeskKind) => {
    setKind(next);
    setIdentityStatus("pending");
    setContentStatus("pending");
    setFeedbackStatus("pending");
    setReportStatus("open");
    setPasswordResetStatus("pending");
    setFlash("");
    setCloseNote("");
    setDismissNote("");
    setUpholdNote("");
  };

  const afterAction = async (excludeId: number, notice: string) => {
    setFlash(notice);
    visitedRef.current.add(excludeId);
    const token = ++gen.current;
    await sleep(ADVANCE_MS);
    if (token !== gen.current || !kind) return;
    setFlash("");
    await loadPane(
      kind, identityStatus, contentStatus, feedbackStatus, reportStatus,
      passwordResetStatus, excludeId, token,
    );
  };

  const skipNext = async () => {
    if (!kind) return;
    const currentId =
      kind === "identity"
        ? identityItem?.id
        : kind === "passwordReset"
          ? passwordResetItem?.id
          : kind === "feedback"
            ? feedbackItem?.id
            : kind === "reports"
              ? reportItem?.id
              : contentRow?.id;
    if (currentId == null) return;
    const prev = {
      identity: identityItem,
      passwordReset: passwordResetItem,
      content: contentRow,
      feedback: feedbackItem,
      report: reportItem,
    };
    visitedRef.current.add(currentId);
    const token = ++gen.current;
    setFlash("");
    const result = await loadPane(
      kind,
      identityStatus,
      contentStatus,
      feedbackStatus,
      reportStatus,
      passwordResetStatus,
      currentId,
      token,
    );
    if (token !== gen.current) return;
    if (result === "empty") {
      // 本轮浏览完时恢复当前显示，避免误显示「本队列已空」
      setIdentityItem(prev.identity);
      setPasswordResetItem(prev.passwordReset);
      setContentRow(prev.content);
      setFeedbackItem(prev.feedback);
      setReportItem(prev.report);
      setFlash("已是最后一条");
    }
  };

  const runIdentity = async (
    fn: () => Promise<IdentityReviewItem>,
    notice: string,
    confirmMsg?: string,
  ) => {
    if (!identityItem) return;
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setBusy(true);
    setError("");
    try {
      const updated = await fn();
      setIdentityItem(updated);
      await afterAction(updated.id, notice);
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const runPasswordReset = async (
    fn: () => Promise<PasswordResetRequestItem>,
    notice: string,
    confirmMsg?: string,
  ) => {
    if (!passwordResetItem) return;
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setBusy(true);
    setError("");
    try {
      const updated = await fn();
      setPasswordResetItem(updated);
      await afterAction(updated.id, notice);
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const runFeedbackClose = async () => {
    if (!feedbackItem) return;
    setBusy(true);
    setError("");
    try {
      const updated = await feedbackApi.close(feedbackItem.id, closeNote);
      setFeedbackItem(updated);
      setCloseNote("");
      await afterAction(updated.id, "已了结");
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const runReportDismiss = async () => {
    if (!reportItem) return;
    if (!dismissNote.trim()) {
      setError("请填写驳回理由");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const updated = await reportsApi.dismiss(reportItem.id, dismissNote.trim());
      setReportItem(updated);
      setDismissNote("");
      await afterAction(updated.id, "已驳回");
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const runReportUphold = async () => {
    if (!reportItem) return;
    setBusy(true);
    setError("");
    try {
      let ends_at: string | null | undefined;
      if (reportItem.target_type === "user") {
        if (mutePermanent) {
          ends_at = null;
        } else {
          if (!muteEnds) {
            setError("请填写禁言结束时间，或勾选永久。");
            setBusy(false);
            return;
          }
          const d = new Date(muteEnds);
          if (Number.isNaN(d.getTime()) || d.getTime() <= Date.now()) {
            setError("结束时间须晚于当前时间。");
            setBusy(false);
            return;
          }
          ends_at = d.toISOString();
        }
      }
      const updated = await reportsApi.uphold(reportItem.id, {
        comment: upholdNote.trim(),
        ...(reportItem.target_type === "user" ? { ends_at } : {}),
      });
      setReportItem(updated);
      setUpholdNote("");
      await afterAction(updated.id, "已成立并处置");
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const tabs = deskTabs({
    canContent, canIdentity, canFeedback, canReports, canPasswordReset,
  });
  const empty =
    kind === "identity"
      ? !identityItem
      : kind === "passwordReset"
        ? !passwordResetItem
        : kind === "feedback"
          ? !feedbackItem
          : kind === "reports"
            ? !reportItem
            : !contentRow;
  const identityLabel = identityItem
    ? IDENTITY_LABELS[identityItem.identity] || identityItem.identity || "未填写"
    : "";

  return (
    <MobilePage title="审核台" back="/m/me" className="m-review">
      {denied ? (
        <p className="mw-hint">你没有审核权限。</p>
      ) : booting ? (
        <p className="mw-hint">加载中…</p>
      ) : (
        <>
          <div className="mw-chips" role="tablist" aria-label="审核类型">
            {tabs.map((t) => (
              <button
                key={t.kind}
                type="button"
                className="mw-chip"
                aria-pressed={kind === t.kind}
                onClick={() => pickKind(t.kind)}
              >
                {t.label}
              </button>
            ))}
          </div>

          {kind === "identity" ? (
            <div className="mw-chips" role="tablist" aria-label="身份审核状态">
              {(["pending", "approved", "rejected"] as IdentityReviewStatus[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  className="mw-chip"
                  aria-pressed={identityStatus === s}
                  onClick={() => setIdentityStatus(s)}
                >
                  {IDENTITY_STATUS_LABELS[s]}
                </button>
              ))}
            </div>
          ) : kind === "passwordReset" ? (
            <div className="mw-chips" role="tablist" aria-label="密码重置状态">
              {(
                [
                  ["pending", "待处理"],
                  ["approved", "已批准"],
                  ["rejected", "已驳回"],
                ] as [PasswordResetStatus, string][]
              ).map(([s, label]) => (
                <button
                  key={s}
                  type="button"
                  className="mw-chip"
                  aria-pressed={passwordResetStatus === s}
                  onClick={() => setPasswordResetStatus(s)}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : kind === "feedback" ? (
            <div className="mw-chips" role="tablist" aria-label="反馈状态">
              {(
                [
                  ["pending", "待处理"],
                  ["closed", "已了结"],
                  ["", "全部"],
                ] as [FeedbackStatus | "", string][]
              ).map(([s, label]) => (
                <button
                  key={label}
                  type="button"
                  className="mw-chip"
                  aria-pressed={feedbackStatus === s}
                  onClick={() => setFeedbackStatus(s)}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : kind === "reports" ? (
            <div className="mw-chips" role="tablist" aria-label="举报案状态">
              {(
                [
                  ["open", "进行中"],
                  ["dismissed", "已驳回"],
                  ["upheld", "成立并处置"],
                  ["", "全部"],
                ] as [ReportStatus | "", string][]
              ).map(([s, label]) => (
                <button
                  key={label}
                  type="button"
                  className="mw-chip"
                  aria-pressed={reportStatus === s}
                  onClick={() => setReportStatus(s)}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : (
            <div className="mw-chips" role="tablist" aria-label="内容审核状态">
              {(
                [
                  ["pending", "待审"],
                  ["approved", "已通过"],
                  ["rejected", "已驳回"],
                  ["removed", "已下架"],
                  ["", "全部"],
                ] as [ReviewStatus | "", string][]
              ).map(([s, label]) => (
                <button
                  key={label}
                  type="button"
                  className="mw-chip"
                  aria-pressed={contentStatus === s}
                  onClick={() => setContentStatus(s)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {error && <div className="mw-alert">{error}</div>}

          {loading ? (
            <p className="mw-hint">加载中…</p>
          ) : empty ? (
            <p className="mw-hint">本队列已空</p>
          ) : kind === "identity" && identityItem ? (
            <div className="desk-pane">
              <div className="desk-meta">
                <span className={"badge " + IDENTITY_STATUS_BADGE[identityItem.status]}>
                  {IDENTITY_STATUS_LABELS[identityItem.status]}
                </span>
                {flash && <span className="badge badge-brand">{flash}</span>}
              </div>
              <h2 className="desk-title">{identityItem.real_name || identityItem.username}</h2>
              <div className="desk-sub">
                <span>用户名 {identityItem.username}</span>
                <span className="sep">·</span>
                <span>{identityLabel}</span>
                {identityItem.verified_by && (
                  <>
                    <span className="sep">·</span>
                    <span>审核人 @{identityItem.verified_by.username}</span>
                  </>
                )}
              </div>
              {identityItem.proofs.length === 0 ? (
                <p className="mw-hint">没有证明材料。</p>
              ) : (
                <div className="desk-proofs">
                  {identityItem.proofs.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className="desk-proof"
                      onClick={() => setLightboxUrl(p.url)}
                      aria-label="查看完整证明图"
                    >
                      <img src={p.url} alt="身份证明" width={1200} height={1600} loading="lazy" />
                      <span className="desk-proof-time">
                        {new Date(p.uploaded_at).toLocaleString("zh-CN", {
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}{" "}
                        上传
                      </span>
                    </button>
                  ))}
                </div>
              )}
              <div className="desk-actions">
                {identityItem.status === "pending" && (
                  <>
                    <button
                      className="btn btn-primary"
                      disabled={busy}
                      onClick={() =>
                        runIdentity(() => identityReviewsApi.approve(identityItem.id), "已通过")
                      }
                    >
                      通过
                    </button>
                    <button
                      className="btn btn-ghost"
                      disabled={busy}
                      onClick={() =>
                        runIdentity(() => identityReviewsApi.reject(identityItem.id), "已驳回")
                      }
                    >
                      驳回
                    </button>
                  </>
                )}
                <button className="btn btn-ghost" disabled={busy || loading} onClick={skipNext}>
                  下一条
                </button>
                <button
                  className="btn btn-danger"
                  disabled={busy}
                  onClick={() =>
                    runIdentity(
                      () => identityReviewsApi.disable(identityItem.id),
                      "账号已停用",
                      "确定停用该账号？对方将立即无法登录。",
                    )
                  }
                >
                  停用账号
                </button>
              </div>
            </div>
          ) : kind === "passwordReset" && passwordResetItem ? (
            <PasswordResetPane
              item={passwordResetItem}
              busy={busy}
              loading={loading}
              flash={flash}
              onApprove={() =>
                runPasswordReset(
                  () => passwordResetApi.approve(passwordResetItem.id),
                  "已批准并重置密码",
                  "确定批准？对方密码将重置为 123456，且首次登录必须修改。",
                )
              }
              onReject={() =>
                runPasswordReset(
                  () => passwordResetApi.reject(passwordResetItem.id),
                  "已驳回",
                )
              }
              onNext={skipNext}
              onLightbox={setLightboxUrl}
            />
          ) : kind === "feedback" && feedbackItem ? (
            <div className="desk-pane">
              <div className="desk-meta">
                <span className={"badge " + FEEDBACK_STATUS_BADGE[feedbackItem.status]}>
                  {FEEDBACK_STATUS_LABELS[feedbackItem.status]}
                </span>
                <span className="type-tag fb">{FEEDBACK_CATEGORY_LABELS[feedbackItem.category]}</span>
                {flash && <span className="badge badge-brand">{flash}</span>}
              </div>
              <h2 className="desk-title">{feedbackItem.title}</h2>
              <div className="desk-sub">
                <span>
                  提交人{" "}
                  {feedbackItem.creator
                    ? feedbackItem.creator.nickname || feedbackItem.creator.username
                    : "匿名"}
                </span>
                <span className="sep">·</span>
                <span>{new Date(feedbackItem.created_at).toLocaleString("zh-CN")}</span>
                {feedbackItem.contact && (
                  <>
                    <span className="sep">·</span>
                    <span>联系 {feedbackItem.contact}</span>
                  </>
                )}
              </div>
              <div className="plain-text" style={{ margin: "12px 0" }}>
                {feedbackItem.description || "（无正文）"}
              </div>
              {feedbackItem.attachments.length > 0 && (
                <div>
                  {feedbackItem.attachments.map((att) => (
                    <div key={att.id} className="mw-att">
                      <a
                        href={att.file_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mw-att-name"
                      >
                        {att.file_name}
                      </a>
                    </div>
                  ))}
                </div>
              )}
              {feedbackItem.status === "pending" && (
                <div className="mw-section">
                  <label className="mw-label">了结说明</label>
                  <textarea
                    className="mw-textarea"
                    rows={3}
                    value={closeNote}
                    onChange={(e) => setCloseNote(e.target.value)}
                    placeholder="可选，署名提交者会收到通知"
                  />
                  <div className="mw-actions">
                    <button className="mw-btn mw-btn-primary" disabled={busy} onClick={runFeedbackClose}>
                      了结
                    </button>
                  </div>
                </div>
              )}
              {feedbackItem.status === "closed" && feedbackItem.close_note && (
                <p className="mw-hint">了结说明：{feedbackItem.close_note}</p>
              )}
              <div className="desk-actions">
                <button className="btn btn-ghost" disabled={busy || loading} onClick={skipNext}>
                  下一条
                </button>
              </div>
            </div>
          ) : kind === "reports" && reportItem ? (
            <div className="desk-pane">
              <div className="desk-meta">
                <span className={"badge " + REPORT_STATUS_BADGE[reportItem.status]}>
                  {REPORT_STATUS_LABELS[reportItem.status]}
                </span>
                {reportItem.target_type && (
                  <span className="type-tag">{REPORT_TARGET_LABELS[reportItem.target_type]}</span>
                )}
                {flash && <span className="badge badge-brand">{flash}</span>}
              </div>
              <h2 className="desk-title">{reportItem.title || "举报案"}</h2>
              <div className="desk-sub">
                {reportItem.target_type &&
                  reportItem.target_type !== "comment" &&
                  reportItem.target_type !== "user" && (
                    <Link
                      to={`/${
                        reportItem.target_type === "tutorial"
                          ? "tutorials"
                          : reportItem.target_type === "activity"
                            ? "activity"
                            : "news"
                      }/${reportItem.target_id}`}
                    >
                      打开对象
                    </Link>
                  )}
                {reportItem.target_type === "user" && (
                  <Link to={`/u/${reportItem.target_id}`}>打开用户</Link>
                )}
                <span className="sep">·</span>
                <span>{new Date(reportItem.created_at).toLocaleString("zh-CN")}</span>
              </div>
              <h3 className="mw-label" style={{ marginTop: 14 }}>举报</h3>
              {(reportItem.filings || []).map((f) => (
                <div key={f.id} className="mw-card">
                  <div className="mw-card-meta" style={{ marginTop: 0 }}>
                    <span>{f.reporter.nickname || f.reporter.username}</span>
                    <span className="mw-dot">·</span>
                    <span>{new Date(f.created_at).toLocaleString("zh-CN")}</span>
                  </div>
                  <div className="plain-text" style={{ marginTop: 6 }}>{f.reason}</div>
                </div>
              ))}
              {reportItem.status === "open" && (
                <div className="mw-section">
                  <label className="mw-label">处理说明</label>
                  <textarea
                    className="mw-textarea"
                    rows={3}
                    value={dismissNote || upholdNote}
                    onChange={(e) => {
                      setDismissNote(e.target.value);
                      setUpholdNote(e.target.value);
                    }}
                    placeholder="驳回必填；成立时可填"
                  />
                  {reportItem.target_type === "user" && (
                    <div style={{ marginTop: 8 }}>
                      <label className="mw-check">
                        <input
                          type="checkbox"
                          checked={mutePermanent}
                          onChange={(e) => setMutePermanent(e.target.checked)}
                        />
                        永久禁言
                      </label>
                      {!mutePermanent && (
                        <input
                          className="mw-input"
                          style={{ marginTop: 8 }}
                          type="datetime-local"
                          value={muteEnds}
                          onChange={(e) => setMuteEnds(e.target.value)}
                        />
                      )}
                    </div>
                  )}
                  <div className="mw-actions">
                    <button className="mw-btn mw-btn-ghost" disabled={busy} onClick={runReportDismiss}>
                      驳回
                    </button>
                    <button className="mw-btn mw-btn-primary" disabled={busy} onClick={runReportUphold}>
                      成立并处置
                    </button>
                  </div>
                </div>
              )}
              {reportItem.status !== "open" && reportItem.resolution_comment && (
                <p className="mw-hint">处理说明：{reportItem.resolution_comment}</p>
              )}
              <div className="desk-actions">
                <button className="btn btn-ghost" disabled={busy || loading} onClick={skipNext}>
                  下一条
                </button>
              </div>
            </div>
          ) : contentRow ? (
            <ReviewPreview
              key={`${contentRow.target_type}-${contentRow.target_id}`}
              review={contentRow}
              flash={flash}
              onModerated={async (updated, notice) => {
                setContentRow(updated);
                await afterAction(updated.id, notice);
              }}
              onSkip={skipNext}
            />
          ) : null}
        </>
      )}

      {lightboxUrl && (
        <div
          className="desk-lightbox"
          role="dialog"
          aria-label="身份证明大图"
          onClick={() => setLightboxUrl("")}
        >
          <img src={lightboxUrl} alt="身份证明" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </MobilePage>
  );
}
