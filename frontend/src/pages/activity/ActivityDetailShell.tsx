import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ActivityDetail,
  ACTIVITY_TYPE_META,
  AUDIENCE_LABELS,
  activityPhase,
} from "../../types/activities";
import type { ActivityStatus } from "../../types/activities";
import Avatar from "../../components/Avatar";
import PageChrome from "../../components/PageChrome";
import AuthorReviewBanner from "../../components/AuthorReviewBanner";
import CommentSection from "../../components/CommentSection";
import ReportButton from "../../components/ReportButton";
import { activityApi } from "../../api/activities";
import { useEmbedMode } from "../../embed";
import CollectionPanel, { CollectionSubmitCard } from "./CollectionPanel";
import DeliberationPanel from "./DeliberationPanel";
import ExhibitionPanel from "./ExhibitionPanel";
import SurveyPanel from "./SurveyPanel";
import type { ActivityViewer } from "./types";

export default function ActivityDetailShell({
  a,
  setActivity,
  user,
  error,
  setError,
  busy,
  setBusy,
}: {
  a: ActivityDetail;
  setActivity: (next: ActivityDetail) => void;
  user: ActivityViewer | null | undefined;
  error: string;
  setError: (error: string) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
}) {
  const navigate = useNavigate();
  const embed = useEmbedMode();
  const [copied, setCopied] = useState(false);
  const isOwner = !!user && a.creator?.id === user.id;
  const canManage = !!user && (isOwner || !!user.can_change_activity);
  const isDeliberation = a.type === "deliberation";
  const isCollection = a.type === "collection";
  const isExhibition = a.type === "exhibition";
  const isSurvey = a.type === "survey";
  const canEditSchema = canManage && a.schema_editable;
  const owesVote = a.owed === "vote";
  const owesSubmit = a.owed === "submit";
  const memberDebt = owesVote || owesSubmit;
  const phase = activityPhase(a.type, a.status);

  const closeLabel = a.is_permanent
    ? "终结活动"
    : isDeliberation
      ? "提前结束投票"
      : isCollection
        ? "提前结束收件"
        : isSurvey
          ? "提前结束征答"
          : "提前结束展示";
  const closeConfirm = a.is_permanent
    ? isCollection
      ? (a.review_enabled ? "终结这个长期活动？将结束收件并进入复审。" : "终结这个长期活动？将结束收件并归档。")
      : "终结这个长期活动？终结后不可再参与，且不可恢复。"
    : isDeliberation
      ? "提前结束投票并结算？"
      : isCollection
        ? (a.review_enabled ? "提前结束收件、进入复审？" : "提前结束收件并归档？")
        : isSurvey
          ? "提前结束征答？"
          : "提前结束展示并结算？";

  const fmtTime = (d: string | null) =>
    d ? new Date(d).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : null;
  const phases = (() => {
    if (isDeliberation || isExhibition || isSurvey) {
      const ns = [];
      if (a.start_at) ns.push({ key: "scheduled", label: "待开始", time: fmtTime(a.start_at) });
      ns.push({
        key: "open",
        label: isExhibition ? "展示中" : isSurvey ? "征答中" : "投票中",
        time: a.is_permanent ? "长期有效" : a.start_at ? null : fmtTime(a.created_at),
      });
      ns.push({ key: "closed", label: "已结束", time: a.is_permanent ? null : fmtTime(a.end_at) });
      return ns;
    }
    const ns = [];
    if (a.start_at) ns.push({ key: "scheduled", label: "待开始", time: fmtTime(a.start_at) });
    ns.push({
      key: "collecting",
      label: "收件中",
      time: a.is_permanent ? "长期有效" : a.start_at ? null : fmtTime(a.created_at),
    });
    if (a.review_enabled) {
      ns.push({ key: "reviewing", label: "复审中", time: a.is_permanent ? null : fmtTime(a.end_at) });
      ns.push({ key: "archived", label: "已归档", time: null });
    } else {
      ns.push({ key: "archived", label: "已归档", time: a.is_permanent ? null : fmtTime(a.end_at) });
    }
    return ns;
  })();
  const currentIndex = Math.max(0, phases.findIndex((p) => p.key === a.status));
  const nowMs = Date.now();
  const t = (iso: string | null) => (iso ? new Date(iso).getTime() : null);
  let currentProgress = 0;
  if (a.status === "scheduled" && a.start_at) {
    const s = t(a.created_at), e = t(a.start_at);
    currentProgress = s && e && e > s ? (nowMs - s) / (e - s) : 0;
  } else if (a.status === "open" || a.status === "collecting") {
    const s = a.start_at ? t(a.start_at) : t(a.created_at), e = t(a.end_at);
    currentProgress = s && e && e > s ? (nowMs - s) / (e - s) : 0;
  }
  currentProgress = Math.max(0, Math.min(1, currentProgress));

  const panelProps = { a, setActivity, user, busy, setBusy, setError };

  const copyLink = async () => {
    try { await navigator.clipboard.writeText(window.location.href); } catch { /* ignore */ }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const doClose = async () => {
    if (!window.confirm(closeConfirm)) return;
    setBusy(true); setError("");
    try { setActivity(await activityApi.close(a.id)); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <PageChrome>
      {!embed && (
      <div className="page-head">
        <div className="container act-head-row">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/activity"); }}>活动</a>
            <span className="sep">/</span>
            <span>{a.title}</span>
          </nav>
          {((canManage && a.status === "scheduled" && !memberDebt) || canEditSchema) && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {canManage && a.status === "scheduled" && !memberDebt && (
                <button className="btn btn-primary btn-sm" onClick={() => navigate(`/activity/${a.id}/edit`)}>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
                  编辑
                </button>
              )}
              {canEditSchema && (
                <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/activity/${a.id}/survey-edit`)}>
                  编辑问卷
                </button>
              )}
            </div>
          )}
        </div>
      </div>
      )}

      <div className="container" style={{ paddingTop: embed ? 0 : "var(--s-8)", paddingBottom: embed ? 0 : "var(--s-16)" }}>
        {error && <div className="alert alert-danger" style={{ margin: "var(--s-4) 0" }}><span>{error}</span></div>}

        <div className="card card-pad">
          <div className="pc-meta" style={{ marginBottom: 8 }}>
            <span className={"act-medal " + phase.medalClass}>
              <span className="act-medal-ico">{phase.emoji}</span>
              {phase.label}
            </span>
            <span className={"act-medal " + ACTIVITY_TYPE_META[a.type].medal}>
              <span className="act-medal-ico">{ACTIVITY_TYPE_META[a.type].emoji}</span>
              {ACTIVITY_TYPE_META[a.type].label}
            </span>
            {(isSurvey || a.audience === "public") && (
              <span className={"badge " + (a.audience === "public" ? "badge-brand" : "badge-neutral")}>
                {AUDIENCE_LABELS[a.audience]}
              </span>
            )}
            {a.is_permanent && <span className="badge badge-neutral">长期有效</span>}
          </div>
          <h1 style={{ margin: "0 0 var(--s-4)" }}>{a.title}</h1>
          {!embed && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              {a.audience === "public" && (
                <button className="btn btn-ghost btn-sm" type="button" onClick={copyLink}>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a4 4 0 0 0 5.7.4l3-3a4 4 0 0 0-5.7-5.7l-1.4 1.4" /><path d="M14 11a4 4 0 0 0-5.7-.4l-3 3a4 4 0 0 0 5.7 5.7l1.4-1.4" /></svg>
                  {copied ? "已复制" : "复制链接"}
                </button>
              )}
              <ReportButton targetType="activity" targetId={a.id} isOwn={isOwner} compact />
            </div>
          )}
        </div>

        {!embed && (
          <AuthorReviewBanner
            kind="activity"
            status={a.review_status}
            comment={a.review_comment}
            extra={
              a.review_status === "pending" && a.status !== "closed" && a.status !== "archived"
                ? (isSurvey
                  ? "活动会按你设的时间推进，但在审核通过前访客/成员看不到、也作答不了。"
                  : "活动会按你设的时间推进，但在审核通过前成员看不到、也投不了。")
                : undefined
            }
          />
        )}

        {owesVote && isDeliberation && <DeliberationPanel {...panelProps} />}
        {owesSubmit && <CollectionSubmitCard {...panelProps} />}

        {memberDebt && canManage && (
          <details className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
            <summary className="section-h" style={{ cursor: "pointer" }}>管理活动</summary>
            <div style={{ marginTop: "var(--s-3)", display: "flex", gap: 8, flexWrap: "wrap" }}>
              {a.status === "scheduled" && (
                <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/activity/${a.id}/edit`)}>编辑</button>
              )}
              {(a.status === "open" || a.status === "collecting") && (
                <button className="btn btn-ghost btn-sm" onClick={() => void doClose()} disabled={busy}>
                  {closeLabel}
                </button>
              )}
            </div>
          </details>
        )}

        {(a.body || (!memberDebt && canManage && (a.status === "open" || a.status === "collecting"))) && (
        <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
          {a.body && <div className="prose" dangerouslySetInnerHTML={{ __html: a.body }} />}
          {!memberDebt && canManage && (a.status === "open" || a.status === "collecting") && (
            <div style={{ marginTop: "var(--s-4)" }}>
              <button className="btn btn-ghost btn-sm" onClick={() => void doClose()} disabled={busy}>
                {closeLabel}
              </button>
            </div>
          )}
        </div>
        )}

        {isSurvey && <SurveyPanel {...panelProps} canManage={canManage} />}

        <div className="card card-pad" style={{ marginTop: "var(--s-4)" }}>
          <h3 className="section-h">时间线</h3>
          <div className="act-stepper">
            {phases.map((p, i) => (
              <div
                key={p.key}
                className={"act-step" + (i === currentIndex ? " is-current" : "") + (i < currentIndex ? " is-done" : "")}
                style={i === currentIndex ? ({ ["--step-progress" as never]: `${Math.round(currentProgress * 100)}%` }) : undefined}
              >
                <div className="act-step-dot">{i < currentIndex ? "✓" : activityPhase(a.type, p.key as ActivityStatus).emoji}</div>
                <div className="act-step-label">{p.label}</div>
                {p.time && <div className="act-step-time">{p.time}</div>}
              </div>
            ))}
          </div>
        </div>

        {isDeliberation && !owesVote && <DeliberationPanel {...panelProps} />}
        {isCollection && <CollectionPanel {...panelProps} hideSubmit={owesSubmit} />}
        {isExhibition && <ExhibitionPanel {...panelProps} />}

        {a.creator && (
          <div className="act-author">
            <Link to={`/u/${a.creator.id}`}><Avatar user={a.creator} size="md" /></Link>
            <div>
              <div className="ac-name">{a.creator.nickname || a.creator.username}</div>
              <div className="ac-desc">@{a.creator.username} · 活动发起人</div>
            </div>
          </div>
        )}
        <CommentSection host={{ activity: a.id }} />
      </div>
    </PageChrome>
  );
}
