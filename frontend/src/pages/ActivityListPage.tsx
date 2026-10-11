import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { activityApi } from "../api/activities";
import { api } from "../api/client";
import {
  ActivityListItem,
  ActivityType,
  ACTIVITY_TYPE_META,
  AUDIENCE_LABELS,
  activityPhase,
} from "../types/activities";
import { REVIEW_STATUS_LABELS } from "../types/reviews";
import { usePagedList } from "../hooks/usePagedList";
import Pagination from "../components/Pagination";
import Avatar from "../components/Avatar";
import AppShell from "../components/AppShell";
import "../styles/list.css";

const PAGE_SIZE = 20;

function formatCountdown(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "即将开始";
  const h = Math.floor(ms / 3600000);
  if (h < 24) return `${h} 小时`;
  return `${Math.floor(h / 24)} 天`;
}

export default function ActivityListPage() {
  const navigate = useNavigate();
  const [typeFilter, setTypeFilter] = useState<ActivityType | "">("");
  const [search, setSearch] = useState("");
  const [mine, setMine] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    api.me().then(() => setLoggedIn(true)).catch(() => setLoggedIn(false));
  }, []);

  const { data: activities, page, setPage, totalPages, loading, error } = usePagedList<ActivityListItem>(
    (params) => {
      const next = { ...params };
      const isMine = next.mine === "1";
      delete next.mine;
      return isMine ? activityApi.mine(next) : activityApi.list(next);
    },
    PAGE_SIZE,
    { type: typeFilter || undefined, search: search || undefined, mine: mine ? "1" : undefined },
  );

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>活动</span>
          </nav>
          <div className="page-head-row">
            <div>
              <h1>活动</h1>
              <p className="section-sub">众议、征集、展示、调研。</p>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {loggedIn && (
                <button className="btn btn-ghost" onClick={() => setMine((v) => !v)}>
                  {mine ? "公开列表" : "我的活动"}
                </button>
              )}
              <button className="btn btn-primary" onClick={() => navigate("/activity/new")}>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
                发起活动
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="container" style={{ paddingBottom: "var(--s-16)" }}>
        <div className="prop-tabs">
          <div className="seg" role="tablist" aria-label="活动类型" style={{ flexWrap: "wrap" }}>
            <button className="seg-btn" type="button" aria-selected={typeFilter === ""} onClick={() => setTypeFilter("")}>全部</button>
            <button className="seg-btn" type="button" aria-selected={typeFilter === "deliberation"} onClick={() => setTypeFilter("deliberation")}>众议</button>
            <button className="seg-btn" type="button" aria-selected={typeFilter === "collection"} onClick={() => setTypeFilter("collection")}>征集</button>
            <button className="seg-btn" type="button" aria-selected={typeFilter === "exhibition"} onClick={() => setTypeFilter("exhibition")}>展示</button>
            <button className="seg-btn" type="button" aria-selected={typeFilter === "survey"} onClick={() => setTypeFilter("survey")}>调研</button>
          </div>
        </div>

        {!loggedIn && (
          <p className="muted" style={{ margin: "var(--s-3) 0 0" }}>
            未登录仅显示公开调研。众议、征集、展示及仅成员调研需登录后查看。
          </p>
        )}

        <div className="prop-filter">
          <div className="input-affix search-affix">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>
            <input className="input" type="search" placeholder="搜索活动…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ margin: "var(--s-6) 0 var(--s-4)" }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
            <span>{error}</span>
          </div>
        )}

        {loading ? (
          <p className="muted" style={{ padding: "var(--s-8) 0" }}>加载中…</p>
        ) : activities.length === 0 ? (
          <div className="prop-empty">
            <p>暂无活动</p>
            <button className="btn btn-primary" onClick={() => navigate("/activity/new")}>发起第一个活动</button>
          </div>
        ) : (
          activities.map((a) => {
            const ph = activityPhase(a.type, a.status);
            return (
              <a key={a.id} className="prop-card" href="#" onClick={(e) => { e.preventDefault(); navigate(`/activity/${a.id}`); }}>
                <div className="pc-title">{a.title}</div>
                <div className="pc-meta">
                  <span className={"act-medal " + ph.medalClass}>
                    <span className="act-medal-ico">{ph.emoji}</span>
                    {ph.label}
                  </span>
                  <span className={"act-medal " + ACTIVITY_TYPE_META[a.type].medal}>
                    <span className="act-medal-ico">{ACTIVITY_TYPE_META[a.type].emoji}</span>
                    {ACTIVITY_TYPE_META[a.type].label}
                  </span>
                  {a.type === "survey" && a.audience && (
                    <span className={"badge " + (a.audience === "public" ? "badge-brand" : "badge-neutral")}>
                      {AUDIENCE_LABELS[a.audience]}
                    </span>
                  )}
                  {a.owed === "vote" && <span className="badge badge-warning">未投</span>}
                  {a.owed === "submit" && <span className="badge badge-warning">未交</span>}
                  {a.review_status && a.review_status !== "approved" && (
                    <span className="badge badge-warning">
                      {REVIEW_STATUS_LABELS[a.review_status] ?? a.review_status}
                    </span>
                  )}
                  <span className="pc-meta-right">
                    {a.creator && (
                      <span className="who">
                        <Avatar user={a.creator} />
                        {a.creator.nickname || a.creator.username}
                      </span>
                    )}
                    {a.status === "scheduled" && a.start_at ? (
                      <span>⏱ 距开始 {formatCountdown(a.start_at)}</span>
                    ) : a.end_at ? (
                      <span>截止 {new Date(a.end_at).toLocaleDateString("zh-CN")}</span>
                    ) : null}
                    <span className="tnum">{new Date(a.created_at).toLocaleDateString("zh-CN")}</span>
                  </span>
                </div>
              </a>
            );
          })
        )}
        {!loading && activities.length > 0 && (
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        )}
      </div>
    </AppShell>
  );
}
