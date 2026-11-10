import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { messagingApi } from "../api/messaging";
import { onMessagingEvent, onMessagingOpen } from "../api/messagingSocket";
import MobilePage from "../components/MobilePage";
import type { Notification } from "../types/messaging";
import {
  NOTIFICATION_CATEGORY_LABELS,
  notificationHref,
  notificationTitle,
} from "../types/messaging";
import "../styles/mobile-work.css";

/**
 * 手机版通知中心（/#/m/notifications）。
 *
 * 桌面版用数字分页器；手机上改成「加载更多」追加，避免在 390px 宽度里塞
 * 一排页码。消息通道事件（notification / 重连）仍会触发首屏刷新。
 */

export default function MobileNotificationsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[] | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (nextPage: number, replace: boolean) => {
    setLoading(true);
    try {
      const data = await messagingApi.listNotifications({ page: String(nextPage) });
      setItems((prev) => (replace || !prev ? data.results : [...prev, ...data.results]));
      setHasMore(!!data.next);
      setTotal(typeof data.count === "number" ? data.count : (data.results || []).length);
      setPage(nextPage);
      setError("");
    } catch (e: any) {
      setError(e?.message || "加载失败");
      if (replace) setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = "通知 · 南汇一中传媒社";
    void load(1, true);
  }, [load]);

  useEffect(() => {
    const refresh = () => void load(1, true);
    const offOpen = onMessagingOpen(refresh);
    const offEv = onMessagingEvent((ev) => {
      if (ev.event === "notification") refresh();
    });
    return () => {
      offOpen();
      offEv();
    };
  }, [load]);

  const openOne = async (n: Notification) => {
    try {
      if (!n.read_at) await messagingApi.markNotificationRead(n.id);
    } catch {
      /* 标记失败也允许继续跳转 */
    }
    const href = notificationHref(n);
    if (!href) {
      void load(1, true);
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
      await load(1, true);
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const unread = (items || []).filter((n) => !n.read_at).length;

  return (
    <MobilePage
      title="通知"
      back="/m/me"
      actions={
        <button type="button" className="mw-link" onClick={markAll} disabled={busy || loading}>
          全部已读
        </button>
      }
    >
      {error && <div className="mw-alert">{error}</div>}
      <p className="mw-hint">
        {items === null
          ? "加载中…"
          : `共 ${total} 条 · 已加载 ${items.length} 条${unread > 0 ? ` · 未读 ${unread}` : ""}`}
      </p>

      {items !== null && items.length === 0 && !loading ? (
        <div className="mw-section">
          <p className="mw-hint" style={{ marginBottom: 0 }}>暂无通知。</p>
        </div>
      ) : (
        (items || []).map((n) => (
          <button
            key={n.id}
            type="button"
            className={"mw-card" + (n.read_at ? "" : " is-unread")}
            onClick={() => void openOne(n)}
          >
            <div className="mw-card-title">{notificationTitle(n)}</div>
            <div className="mw-card-meta">
              <span className="badge badge-brand">{NOTIFICATION_CATEGORY_LABELS[n.category]}</span>
              {!n.read_at && <span className="badge badge-warning">未读</span>}
              <span className="tnum">{new Date(n.created_at).toLocaleString("zh-CN")}</span>
            </div>
          </button>
        ))
      )}

      {hasMore && (
        <button
          type="button"
          className="mw-more"
          disabled={loading}
          onClick={() => void load(page + 1, false)}
        >
          {loading ? "加载中…" : "加载更多"}
        </button>
      )}
    </MobilePage>
  );
}
