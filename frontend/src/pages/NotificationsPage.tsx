import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { messagingApi } from "../api/messaging";
import { onMessagingEvent, onMessagingOpen } from "../api/messagingSocket";
import AppShell from "../components/AppShell";
import Pagination from "../components/Pagination";
import { usePagedList } from "../hooks/usePagedList";
import type { Notification } from "../types/messaging";
import {
  NOTIFICATION_CATEGORY_LABELS,
  notificationHref,
  notificationTitle,
} from "../types/messaging";
import "../styles/list.css";

const PAGE_SIZE = 20;

export default function NotificationsPage() {
  const navigate = useNavigate();
  const { data, page, setPage, totalPages, loading, error, refetch } = usePagedList<Notification>(
    (params) => messagingApi.listNotifications(params),
    PAGE_SIZE,
  );
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.title = "通知 · 传媒社";
  }, []);

  useEffect(() => {
    const refresh = () => refetch();
    const offOpen = onMessagingOpen(refresh);
    const offEv = onMessagingEvent((ev) => {
      if (ev.event === "notification") refresh();
    });
    return () => { offOpen(); offEv(); };
    // refetch 每次 render 换身份；只订阅一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openOne = async (n: Notification) => {
    try {
      if (!n.read_at) await messagingApi.markNotificationRead(n.id);
    } catch { /* still navigate */ }
    const href = notificationHref(n);
    if (!href) {
      refetch();
      return;
    }
    if (href.startsWith("http://") || href.startsWith("https://")) {
      window.location.href = href;
      return;
    }
    navigate(href);
  };

  const markAll = async () => {
    setBusy(true);
    try {
      await messagingApi.markAllNotificationsRead();
      refetch();
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>通知</span>
          </nav>
          <div className="page-head-row">
            <h1>通知</h1>
            <button className="btn btn-ghost btn-sm" type="button" onClick={markAll} disabled={busy || loading}>
              全部已读
            </button>
          </div>
          <p className="section-sub">系统投递的站内提醒，不是私信。</p>
        </div>
      </div>
      <div className="container" style={{ paddingTop: "var(--s-6)", paddingBottom: "var(--s-16)" }}>
        {error && (
          <div className="alert alert-danger" style={{ margin: "0 0 var(--s-4)" }}>
            <span>{error}</span>
          </div>
        )}
        {loading ? (
          <p className="muted" style={{ padding: "var(--s-8) 0" }}>加载中…</p>
        ) : data.length === 0 ? (
          <div className="prop-empty">
            <p>暂无通知。</p>
          </div>
        ) : (
          data.map((n) => (
            <a
              key={n.id}
              className="prop-card"
              href="#"
              onClick={(e) => { e.preventDefault(); void openOne(n); }}
              style={n.read_at ? undefined : { borderColor: "var(--brand-200)" }}
            >
              <div className="pc-title">{notificationTitle(n)}</div>
              <div className="pc-meta">
                <span className="badge badge-brand">{NOTIFICATION_CATEGORY_LABELS[n.category]}</span>
                {!n.read_at && <span className="badge badge-warning">未读</span>}
                <span className="tnum">{new Date(n.created_at).toLocaleString("zh-CN")}</span>
              </div>
            </a>
          ))
        )}
        {!loading && data.length > 0 && (
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        )}
      </div>
    </AppShell>
  );
}
