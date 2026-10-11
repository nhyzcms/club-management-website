import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api } from "../api/client";
import { identityReviewsApi } from "../api/identityReviews";
import { reviewsApi } from "../api/reviews";
import { feedbackApi } from "../api/feedback";
import { reportsApi } from "../api/reports";
import ReviewPreview from "./review/ReviewPreview";
import {
  IDENTITY_LABELS,
  IDENTITY_STATUS_BADGE,
  IDENTITY_STATUS_LABELS,
  type IdentityReviewItem,
  type IdentityReviewStatus,
} from "../types/identityReviews";
import {
  type ReviewItem,
  type ReviewStatus,
  type ReviewTargetType,
  TARGET_TYPE_LABELS,
} from "../types/reviews";
import {
  type FeedbackDetail,
  type FeedbackStatus,
  FEEDBACK_CATEGORY_LABELS,
  FEEDBACK_STATUS_BADGE,
  FEEDBACK_STATUS_LABELS,
} from "../types/feedback";
import {
  type ReportCase,
  type ReportStatus,
  REPORT_STATUS_BADGE,
  REPORT_STATUS_LABELS,
  REPORT_TARGET_LABELS,
} from "../types/reports";
import "../styles/list.css";
import "../styles/form.css";
import "../styles/detail.css";

type DeskKind = "identity" | ReviewTargetType | "feedback" | "reports";

const ADVANCE_MS = 900;
const CONTENT_KINDS: ReviewTargetType[] = ["news", "activity", "tutorial"];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function firstOf<T extends { id: number }>(
  fetchPage: (page: number) => Promise<{ results: T[]; next: string | null }>,
  excludeId?: number,
  skip?: Set<number>,
): Promise<T | null> {
  let page = 1;
  for (;;) {
    const data = await fetchPage(page);
    const hit = (data.results || []).find(
      (row) => row.id !== excludeId && !(skip && skip.has(row.id)),
    );
    if (hit) return hit;
    if (!data.next) return null;
    page += 1;
  }
}

async function firstIdentity(status: IdentityReviewStatus, excludeId?: number, skip?: Set<number>) {
  return firstOf((page) => identityReviewsApi.list({ status, page: String(page) }), excludeId, skip);
}

async function firstContent(type: ReviewTargetType, status: ReviewStatus | "", excludeId?: number, skip?: Set<number>) {
  return firstOf(async (page) => {
    const params: Record<string, string> = { ordering: "created_at", page: String(page) };
    if (status) params.status = status;
    const data = await reviewsApi.list(params);
    return {
      results: (data.results || []).filter((row) => row.target_type === type),
      next: data.next,
    };
  }, excludeId, skip);
}

async function firstFeedback(status: FeedbackStatus | "", excludeId?: number, skip?: Set<number>) {
  return firstOf((page) => {
    const params: Record<string, string> = { ordering: "created_at", page: String(page) };
    if (status) params.status = status;
    return feedbackApi.list(params);
  }, excludeId, skip);
}

async function firstReport(status: ReportStatus | "", excludeId?: number, skip?: Set<number>) {
  return firstOf((page) => {
    const params: Record<string, string> = { ordering: "created_at", page: String(page) };
    if (status) params.status = status;
    return reportsApi.list(params);
  }, excludeId, skip);
}

export default function ReviewQueuePage() {
  const navigate = useNavigate();
  const gen = useRef(0);
  // 本轮已浏览/已处理的条目（「下一条」与处理动作后前进都跳过它们），切桌/切状态时重置
  const visitedRef = useRef<Set<number>>(new Set());

  const [canContent, setCanContent] = useState(false);
  const [canIdentity, setCanIdentity] = useState(false);
  const [canFeedback, setCanFeedback] = useState(false);
  const [canReports, setCanReports] = useState(false);
  const [denied, setDenied] = useState(false);
  const [booting, setBooting] = useState(true);

  const [kind, setKind] = useState<DeskKind | null>(null);
  const [identityStatus, setIdentityStatus] = useState<IdentityReviewStatus>("pending");
  const [contentStatus, setContentStatus] = useState<ReviewStatus | "">("pending");
  const [feedbackStatus, setFeedbackStatus] = useState<FeedbackStatus | "">("pending");
  const [reportStatus, setReportStatus] = useState<ReportStatus | "">("open");

  const [identityItem, setIdentityItem] = useState<IdentityReviewItem | null>(null);
  const [contentRow, setContentRow] = useState<ReviewItem | null>(null);
  const [feedbackItem, setFeedbackItem] = useState<FeedbackDetail | null>(null);
  const [reportItem, setReportItem] = useState<ReportCase | null>(null);

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

  const loadPane = useCallback(async (
    nextKind: DeskKind,
    idStatus: IdentityReviewStatus,
    cStatus: ReviewStatus | "",
    fStatus: FeedbackStatus | "",
    rStatus: ReportStatus | "",
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
        return item ? "ok" : "empty";
      } else if (nextKind === "feedback") {
        const row = await firstFeedback(fStatus, excludeId, skip);
        const detail = row ? await feedbackApi.get(row.id) : null;
        if (token != null && token !== gen.current) return "ok";
        setIdentityItem(null);
        setContentRow(null);
        setFeedbackItem(detail);
        setReportItem(null);
        return row ? "ok" : "empty";
      } else if (nextKind === "reports") {
        const row = await firstReport(rStatus, excludeId, skip);
        if (token != null && token !== gen.current) return "ok";
        setIdentityItem(null);
        setContentRow(null);
        setFeedbackItem(null);
        setReportItem(row);
        return row ? "ok" : "empty";
      } else {
        const row = await firstContent(nextKind, cStatus, excludeId, skip);
        if (token != null && token !== gen.current) return "ok";
        setIdentityItem(null);
        setContentRow(row);
        setFeedbackItem(null);
        setReportItem(null);
        return row ? "ok" : "empty";
      }
    } catch (e: any) {
      if (token != null && token !== gen.current) return "ok";
      setError(e.message || "加载失败");
      setIdentityItem(null);
      setContentRow(null);
      setFeedbackItem(null);
      setReportItem(null);
      return "error";
    } finally {
      if (token == null || token === gen.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.me()
      .then(async (d: any) => {
        const content = !!d.user?.permissions?.can_review_content;
        const identity = !!d.user?.permissions?.can_review_identity;
        const feedback = !!d.user?.permissions?.can_view_feedback;
        const reports = !!d.user?.permissions?.can_handle_reports;
        if (cancelled) return;
        setCanContent(content);
        setCanIdentity(identity);
        setCanFeedback(feedback);
        setCanReports(reports);
        if (!content && !identity && !feedback && !reports) {
          setDenied(true);
          setBooting(false);
          return;
        }
        const order: DeskKind[] = [];
        if (identity) order.push("identity");
        if (content) order.push(...CONTENT_KINDS);
        if (feedback) order.push("feedback");
        if (reports) order.push("reports");
        const probes = await Promise.all(order.map(async (k) => {
          try {
            if (k === "identity") return { k, hit: await firstIdentity("pending") };
            if (k === "feedback") return { k, hit: await firstFeedback("pending") };
            if (k === "reports") return { k, hit: await firstReport("open") };
            return { k, hit: await firstContent(k, "pending") };
          } catch {
            return { k, hit: null };
          }
        }));
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
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (booting || !kind) return;
    const token = ++gen.current;
    visitedRef.current = new Set();  // 切桌 / 切状态：新一轮浏览从头开始
    setFlash("");
    loadPane(kind, identityStatus, contentStatus, feedbackStatus, reportStatus, undefined, token);
  }, [booting, kind, identityStatus, contentStatus, feedbackStatus, reportStatus, loadPane]);

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
    setFlash("");
    setCloseNote("");
    setDismissNote("");
    setUpholdNote("");
  };

  const afterAction = async (excludeId: number, notice: string) => {
    setFlash(notice);
    visitedRef.current.add(excludeId);  // 已处理的条目不再重复出现
    const token = ++gen.current;
    await sleep(ADVANCE_MS);
    if (token !== gen.current || !kind) return;
    setFlash("");
    await loadPane(kind, identityStatus, contentStatus, feedbackStatus, reportStatus, excludeId, token);
  };

  // 「下一条」：不处理当前条目，直接跳到队列中下一条未浏览的
  const skipNext = async () => {
    if (!kind) return;
    const currentId = kind === "identity" ? identityItem?.id
      : kind === "feedback" ? feedbackItem?.id
      : kind === "reports" ? reportItem?.id
      : contentRow?.id;
    if (currentId == null) return;
    // 本轮浏览完时恢复当前显示，避免误显示「本队列已空」
    const prev = { identity: identityItem, content: contentRow, feedback: feedbackItem, report: reportItem };
    visitedRef.current.add(currentId);
    const token = ++gen.current;
    setFlash("");
    const result = await loadPane(kind, identityStatus, contentStatus, feedbackStatus, reportStatus, currentId, token);
    if (token !== gen.current) return;
    if (result === "empty") {
      setIdentityItem(prev.identity);
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
      setError(e.message || "操作失败");
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
      setError(e.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const runReportDismiss = async () => {
    if (!reportItem) return;
    if (!dismissNote.trim()) { setError("请填写驳回理由"); return; }
    setBusy(true);
    setError("");
    try {
      const updated = await reportsApi.dismiss(reportItem.id, dismissNote.trim());
      setReportItem(updated);
      setDismissNote("");
      await afterAction(updated.id, "已驳回");
    } catch (e: any) {
      setError(e.message || "操作失败");
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
        if (mutePermanent) ends_at = null;
        else {
          if (!muteEnds) { setError("请填写禁言结束时间，或勾选永久。"); setBusy(false); return; }
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
      setError(e.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const empty = kind === "identity" ? !identityItem
    : kind === "feedback" ? !feedbackItem
    : kind === "reports" ? !reportItem
    : !contentRow;
  const identityLabel = identityItem
    ? (IDENTITY_LABELS[identityItem.identity] || identityItem.identity || "未填写")
    : "";

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>审核队列</span>
          </nav>
          <div className="page-head-row">
            <div>
              <h1>审核台</h1>
              <p className="section-sub">发布审核、意见反馈、举报案与身份证明分桌处理，处理后自动进入下一条。</p>
            </div>
          </div>
        </div>
      </div>

      <div className="container" style={{ paddingBottom: "var(--s-16)" }}>
        {denied ? (
          <p className="task-empty">你没有审核权限。</p>
        ) : booting ? (
          <p className="task-empty">加载中…</p>
        ) : (
          <>
            <div className="filter-bar" role="tablist" aria-label="审核类型">
              {canIdentity && (
                <button className="chip" aria-pressed={kind === "identity"}
                        onClick={() => pickKind("identity")}>身份</button>
              )}
              {canContent && CONTENT_KINDS.map((k) => (
                <button key={k} className="chip" aria-pressed={kind === k}
                        onClick={() => pickKind(k)}>{TARGET_TYPE_LABELS[k]}</button>
              ))}
              {canFeedback && (
                <button className="chip" aria-pressed={kind === "feedback"}
                        onClick={() => pickKind("feedback")}>意见反馈</button>
              )}
              {canReports && (
                <button className="chip" aria-pressed={kind === "reports"}
                        onClick={() => pickKind("reports")}>举报案</button>
              )}
            </div>

            {kind === "identity" ? (
              <div className="filter-bar" role="tablist" aria-label="身份审核状态">
                {(["pending", "approved", "rejected"] as IdentityReviewStatus[]).map((s) => (
                  <button key={s} className="chip" aria-pressed={identityStatus === s}
                          onClick={() => setIdentityStatus(s)}>
                    {IDENTITY_STATUS_LABELS[s]}
                  </button>
                ))}
              </div>
            ) : kind === "feedback" ? (
              <div className="filter-bar" role="tablist" aria-label="反馈状态">
                <button className="chip" aria-pressed={feedbackStatus === "pending"}
                        onClick={() => setFeedbackStatus("pending")}>待处理</button>
                <button className="chip" aria-pressed={feedbackStatus === "closed"}
                        onClick={() => setFeedbackStatus("closed")}>已了结</button>
                <button className="chip" aria-pressed={feedbackStatus === ""}
                        onClick={() => setFeedbackStatus("")}>全部</button>
              </div>
            ) : kind === "reports" ? (
              <div className="filter-bar" role="tablist" aria-label="举报案状态">
                <button className="chip" aria-pressed={reportStatus === "open"}
                        onClick={() => setReportStatus("open")}>进行中</button>
                <button className="chip" aria-pressed={reportStatus === "dismissed"}
                        onClick={() => setReportStatus("dismissed")}>已驳回</button>
                <button className="chip" aria-pressed={reportStatus === "upheld"}
                        onClick={() => setReportStatus("upheld")}>成立并处置</button>
                <button className="chip" aria-pressed={reportStatus === ""}
                        onClick={() => setReportStatus("")}>全部</button>
              </div>
            ) : (
              <div className="filter-bar" role="tablist" aria-label="内容审核状态">
                <button className="chip" aria-pressed={contentStatus === "pending"}
                        onClick={() => setContentStatus("pending")}>待审</button>
                <button className="chip" aria-pressed={contentStatus === "approved"}
                        onClick={() => setContentStatus("approved")}>已通过</button>
                <button className="chip" aria-pressed={contentStatus === "rejected"}
                        onClick={() => setContentStatus("rejected")}>已驳回</button>
                <button className="chip" aria-pressed={contentStatus === "removed"}
                        onClick={() => setContentStatus("removed")}>已下架</button>
                <button className="chip" aria-pressed={contentStatus === ""}
                        onClick={() => setContentStatus("")}>全部</button>
              </div>
            )}

            {error && <div className="alert alert-warning" style={{ marginBottom: 12 }}>{error}</div>}

            {loading ? (
              <p className="task-empty">加载中…</p>
            ) : empty ? (
              <p className="task-empty">本队列已空</p>
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
                  <p className="empty-text">没有证明材料。</p>
                ) : (
                  <div className="desk-proofs">
                    {identityItem.proofs.map((p) => (
                      <button key={p.id} type="button" className="desk-proof"
                              onClick={() => setLightboxUrl(p.url)}
                              aria-label="查看完整证明图">
                        <img src={p.url} alt="身份证明" width={1200} height={1600} />
                        <span className="desk-proof-time">
                          {new Date(p.uploaded_at).toLocaleString("zh-CN", {
                            month: "2-digit", day: "2-digit",
                            hour: "2-digit", minute: "2-digit",
                          })} 上传
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                <div className="desk-actions">
                  {identityItem.status === "pending" && (
                    <>
                      <button className="btn btn-primary" disabled={busy}
                              onClick={() => runIdentity(
                                () => identityReviewsApi.approve(identityItem.id),
                                "已通过",
                              )}>通过</button>
                      <button className="btn btn-ghost" disabled={busy}
                              onClick={() => runIdentity(
                                () => identityReviewsApi.reject(identityItem.id),
                                "已驳回",
                              )}>驳回</button>
                    </>
                  )}
                  <button className="btn btn-ghost" disabled={busy || loading} onClick={skipNext}>
                    下一条
                  </button>
                  <button className="btn btn-danger" disabled={busy}
                          onClick={() => runIdentity(
                            () => identityReviewsApi.disable(identityItem.id),
                            "账号已停用",
                            "确定停用该账号？对方将立即无法登录。",
                          )}>停用账号</button>
                </div>
              </div>
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
                  <span>提交人 {feedbackItem.creator ? (feedbackItem.creator.nickname || feedbackItem.creator.username) : "匿名"}</span>
                  <span className="sep">·</span>
                  <span>{new Date(feedbackItem.created_at).toLocaleString("zh-CN")}</span>
                  {feedbackItem.contact && (
                    <>
                      <span className="sep">·</span>
                      <span>联系 {feedbackItem.contact}</span>
                    </>
                  )}
                </div>
                <div className="plain-text" style={{ margin: "12px 0" }}>{feedbackItem.description || "（无正文）"}</div>
                {feedbackItem.attachments.length > 0 && (
                  <div className="att-list">
                    {feedbackItem.attachments.map((att) => (
                      <div key={att.id} className="att-item">
                        <a href={att.file_url} target="_blank" rel="noopener noreferrer" className="att-name">{att.file_name}</a>
                      </div>
                    ))}
                  </div>
                )}
                {feedbackItem.status === "pending" && (
                  <div className="card card-pad" style={{ marginTop: 12 }}>
                    <label className="label">了结说明</label>
                    <textarea className="textarea" rows={3} value={closeNote} onChange={(e) => setCloseNote(e.target.value)} placeholder="可选，署名提交者会收到通知" />
                    <div className="desk-actions" style={{ marginTop: 8 }}>
                      <button className="btn btn-primary" disabled={busy} onClick={runFeedbackClose}>了结</button>
                    </div>
                  </div>
                )}
                {feedbackItem.status === "closed" && feedbackItem.close_note && (
                  <p className="empty-text">了结说明：{feedbackItem.close_note}</p>
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
                  {reportItem.target_type && reportItem.target_type !== "comment" && reportItem.target_type !== "user" && (
                    <Link to={`/${reportItem.target_type === "tutorial" ? "tutorials" : reportItem.target_type === "activity" ? "activity" : "news"}/${reportItem.target_id}`}>
                      打开对象
                    </Link>
                  )}
                  {reportItem.target_type === "user" && (
                    <Link to={`/u/${reportItem.target_id}`}>打开用户</Link>
                  )}
                  <span className="sep">·</span>
                  <span>{new Date(reportItem.created_at).toLocaleString("zh-CN")}</span>
                </div>
                <h3 className="section-h" style={{ marginTop: 16 }}>举报</h3>
                {(reportItem.filings || []).map((f) => (
                  <div key={f.id} className="card card-pad" style={{ marginBottom: 8 }}>
                    <div className="desk-sub">
                      <span>{f.reporter.nickname || f.reporter.username}</span>
                      <span className="sep">·</span>
                      <span>{new Date(f.created_at).toLocaleString("zh-CN")}</span>
                    </div>
                    <div className="plain-text">{f.reason}</div>
                  </div>
                ))}
                {reportItem.status === "open" && (
                  <div className="card card-pad" style={{ marginTop: 12 }}>
                    <label className="label">处理说明</label>
                    <textarea className="textarea" rows={3} value={dismissNote || upholdNote}
                              onChange={(e) => { setDismissNote(e.target.value); setUpholdNote(e.target.value); }}
                              placeholder="驳回必填；成立时可填" />
                    {reportItem.target_type === "user" && (
                      <div style={{ marginTop: 8 }}>
                        <label className="check">
                          <input type="checkbox" checked={mutePermanent} onChange={(e) => setMutePermanent(e.target.checked)} />
                          永久禁言
                        </label>
                        {!mutePermanent && (
                          <input className="input" type="datetime-local" value={muteEnds} onChange={(e) => setMuteEnds(e.target.value)} />
                        )}
                      </div>
                    )}
                    <div className="desk-actions" style={{ marginTop: 8 }}>
                      <button className="btn btn-ghost" disabled={busy} onClick={runReportDismiss}>驳回</button>
                      <button className="btn btn-primary" disabled={busy} onClick={runReportUphold}>成立并处置</button>
                    </div>
                  </div>
                )}
                {reportItem.status !== "open" && reportItem.resolution_comment && (
                  <p className="empty-text">处理说明：{reportItem.resolution_comment}</p>
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
      </div>

      {lightboxUrl && (
        <div className="desk-lightbox" role="dialog" aria-label="身份证明大图"
             onClick={() => setLightboxUrl("")}>
          <img src={lightboxUrl} alt="身份证明" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </AppShell>
  );
}
