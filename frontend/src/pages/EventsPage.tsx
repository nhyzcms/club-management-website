import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import Pagination from "../components/Pagination";
import { usePagedList } from "../hooks/usePagedList";
import { api } from "../api/client";
import { eventApi } from "../api/events";
import { EVENT_STATUS_META, type Event } from "../types/events";
import { ICONS } from "../components/icons";
import "../styles/list.css";

const PAGE_SIZE = 20;

const TABS: { key: string; label: string }[] = [
  { key: "", label: "全部" },
  { key: "active", label: "进行中" },
  { key: "scheduled", label: "待开始" },
  { key: "ended", label: "已结束" },
  { key: "archived", label: "已归档" },
];

function fmt(iso: string | null): string {
  if (!iso) return "未设结束";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function EventsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("");
  const [canCreate, setCanCreate] = useState(false);

  useEffect(() => {
    document.title = "活动 · 南汇一中传媒社";
    api.me()
      .then((d: any) => setCanCreate(!!d.profile?.is_verified))
      .catch(() => setCanCreate(false));
  }, []);

  const { data, page, setPage, totalPages, loading, error } = usePagedList<Event>(
    (params) => eventApi.list(tab ? { ...params, status: tab } : params),
    PAGE_SIZE,
    { tab },
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
              <p className="section-sub">限时开放，到点自动关闭。参与方式由具体活动决定。</p>
            </div>
            {canCreate && (
              <button className="btn btn-primary" onClick={() => navigate("/events/new")}>
                <span className="ico">{ICONS.plus}</span>发起活动
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="container" style={{ paddingBottom: "var(--s-16)" }}>
        <div className="seg" role="tablist" aria-label="活动状态" style={{ flexWrap: "wrap", marginBottom: "var(--s-6)" }}>
          {TABS.map((t) => (
            <button
              key={t.key}
              className="seg-btn"
              type="button"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error && <div className="alert alert-danger">{error}</div>}
        {loading ? (
          <p className="task-empty">加载中…</p>
        ) : data.length === 0 ? (
          <div className="prop-empty">
            <p>暂无活动</p>
          </div>
        ) : (
          data.map((e) => {
            const tone = EVENT_STATUS_META[e.status]?.tone ?? "muted";
            return (
              <a
                key={e.id}
                className="prop-card"
                href="#"
                onClick={(ev) => { ev.preventDefault(); navigate(`/events/${e.id}`); }}
              >
                <div className="pc-title">{e.title}</div>
                <div className="pc-meta">
                  <span className={`badge badge-${tone}`}>{e.status_label}</span>
                  <span>{fmt(e.start_at)} — {fmt(e.end_at)}</span>
                  {e.visibility === "members" && <span>仅成员</span>}
                </div>
                {e.summary && <div className="pc-excerpt">{e.summary}</div>}
              </a>
            );
          })
        )}
        {!loading && <Pagination page={page} totalPages={totalPages} onChange={setPage} />}
      </div>
    </AppShell>
  );
}
