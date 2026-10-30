import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api } from "../api/client";
import { eventApi } from "../api/events";
import { EVENT_STATUS_META, type Event } from "../types/events";
import "../styles/list.css";
import "../styles/news.css";

function fmt(iso: string | null): string {
  if (!iso) return "未设结束";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function EventDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [event, setEvent] = useState<Event | null>(null);
  const [me, setMe] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    eventApi
      .get(Number(id))
      .then(setEvent)
      .catch((e: any) => setError(e?.message || "活动不存在或不可见"));
  }

  useEffect(() => {
    load();
    api.me().then(setMe).catch(() => setMe(null));
  }, [id]);

  const permissions: string[] = me?.user?.permissions ?? [];
  const canManage = !!me && !!event && (
    me.user?.id === event.organizer?.id ||
    permissions.includes("events.manage_events") ||
    me.role?.variant === "superadmin"
  );

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      load();
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!event) return;
    if (!window.confirm("删除这个草稿？该操作不可恢复。")) return;
    setBusy(true);
    try {
      await eventApi.remove(event.id);
      navigate("/events");
    } catch (e: any) {
      setError(e?.message || "删除失败");
    } finally {
      setBusy(false);
    }
  }

  if (error && !event) {
    return (
      <AppShell>
        <div className="container" style={{ padding: "var(--s-16) 0" }}>
          <div className="alert alert-danger">{error}</div>
        </div>
      </AppShell>
    );
  }

  if (!event) {
    return (
      <AppShell>
        <div className="container" style={{ padding: "var(--s-16) 0" }}>
          <p className="task-empty">加载中…</p>
        </div>
      </AppShell>
    );
  }

  const tone = EVENT_STATUS_META[event.status]?.tone ?? "muted";

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/events"); }}>活动</a>
            <span className="sep">/</span>
            <span>{event.title}</span>
          </nav>
          <h1>{event.title}</h1>
          <div className="section-sub" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <span className={`badge badge-${tone}`}>{event.status_label}</span>
            <span>{fmt(event.start_at)} — {fmt(event.end_at)}</span>
            {event.visibility === "members" && <span>仅成员</span>}
            {event.organizer && <span>组织者 {event.organizer.nickname || event.organizer.username}</span>}
          </div>
        </div>
      </div>

      <div className="container" style={{ paddingBottom: "var(--s-16)", maxWidth: 820 }}>
        {error && <div className="alert alert-danger" style={{ marginBottom: "var(--s-4)" }}>{error}</div>}

        {event.summary && (
          <p className="section-sub" style={{ marginBottom: "var(--s-5)" }}>{event.summary}</p>
        )}

        {event.body ? (
          <div className="prose" dangerouslySetInnerHTML={{ __html: event.body }} />
        ) : (
          <p className="task-empty">这个活动还没有正文。</p>
        )}

        <div
          style={{
            marginTop: "var(--s-10)",
            padding: "var(--s-5)",
            border: "1px dashed var(--line)",
            borderRadius: "var(--r-3)",
            color: "var(--ink-500)",
          }}
        >
          {event.module_key
            ? `参与方式：${event.module_key}（该形态尚未接入）`
            : "该活动为展示型，没有额外的参与流程。"}
        </div>

        {canManage && (
          <div style={{ display: "flex", gap: 12, marginTop: "var(--s-8)", flexWrap: "wrap" }}>
            {event.status === "draft" && (
              <button className="btn btn-primary" disabled={busy}
                onClick={() => act(() => eventApi.publish(event.id))}>
                发布
              </button>
            )}
            {event.status === "ended" && (
              <button className="btn btn-secondary" disabled={busy}
                onClick={() => act(() => eventApi.archive(event.id))}>
                归档
              </button>
            )}
            {event.status === "draft" && (
              <button className="btn btn-danger" disabled={busy} onClick={remove}>
                删除草稿
              </button>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
