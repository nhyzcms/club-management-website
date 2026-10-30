import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSitePolicy } from "../api/sitePolicy";
import AppShell from "../components/AppShell";
import {
  INBOX_REASON_LABELS,
  type InboxItem,
  type InboxResponse,
} from "../types/inbox";
import { ACTIVITY_TYPE_META } from "../types/activities";
import { STATUS_LABELS } from "../types/tasks";
import "../styles/list.css";

function itemTitle(item: InboxItem): string {
  if (item.kind === "activity" && item.activity) return item.activity.title;
  if (item.kind === "task" && item.task) return item.task.title;
  if (item.kind === "conversation" && item.conversation) {
    return item.conversation.title
      || item.conversation.last_message?.content
      || "未读会话";
  }
  return "待办";
}

function itemPath(item: InboxItem): string | null {
  if (item.kind === "activity" && item.activity) return `/activity/${item.activity.id}`;
  if (item.kind === "task" && item.task) return `/tasks/${item.task.id}`;
  if (item.kind === "conversation" && item.conversation) return `/messages/${item.conversation.id}`;
  return null;
}

function itemKindLabel(item: InboxItem): string {
  if (item.kind === "activity" && item.activity) return ACTIVITY_TYPE_META[item.activity.type].label;
  if (item.kind === "task") return "任务";
  return "会话";
}

export default function InboxPage() {
  const navigate = useNavigate();
  const policy = useSitePolicy();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    document.title = "待办 · 传媒社";
    api.me()
      .then((d: any) => {
        const verified = !!d.profile?.is_verified;
        if (!verified) {
          navigate("/profile?tab=verification", { replace: true });
          return;
        }
        return api.inbox() as Promise<InboxResponse>;
      })
      .then((body) => {
        if (body) setItems(body.results);
      })
      .catch((e: any) => {
        if (e?.status === 403 || e?.status === 401) {
          navigate("/profile?tab=verification", { replace: true });
          return;
        }
        setError(e?.message || "加载失败");
        setItems([]);
      });
  }, [navigate]);

  // 私信关闭时，待办列表不再展示会话条目（与私信入口隐藏保持一致）。
  const visibleItems = items === null ? null : items.filter((i) => policy.dms_enabled || i.kind !== "conversation");

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>待办</span>
          </nav>
          <h1>待办</h1>
          <p className="section-sub">当前你仍欠的行动：互动、任务。</p>
        </div>
      </div>
      <div className="container" style={{ paddingTop: "var(--s-6)", paddingBottom: "var(--s-16)" }}>
        {error && (
          <div className="alert alert-danger" style={{ margin: "0 0 var(--s-4)" }}>
            <span>{error}</span>
          </div>
        )}
        {visibleItems === null ? (
          <p className="muted" style={{ padding: "var(--s-8) 0" }}>加载中…</p>
        ) : visibleItems.length === 0 ? (
          <div className="prop-empty">
            <p>没有待办。去看看互动或任务。</p>
            <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
              <button className="btn btn-primary" onClick={() => navigate("/activity")}>互动</button>
              <button className="btn btn-ghost" onClick={() => navigate("/tasks")}>任务</button>
            </div>
          </div>
        ) : (
          visibleItems.map((item, i) => {
            const path = itemPath(item);
            return (
              <a
                key={`${item.kind}-${path || i}`}
                className="prop-card"
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  if (path) navigate(path);
                }}
              >
                <div className="pc-title">{itemTitle(item)}</div>
                <div className="pc-meta">
                  {item.pinned && <span className="badge badge-warning">即将截止</span>}
                  <span className="badge badge-brand">{INBOX_REASON_LABELS[item.reason]}</span>
                  <span>{itemKindLabel(item)}</span>
                  {item.kind === "task" && item.task && <span>{STATUS_LABELS[item.task.status]}</span>}
                  {item.end_at && (
                    <span className="tnum">截止 {new Date(item.end_at).toLocaleString("zh-CN")}</span>
                  )}
                </div>
              </a>
            );
          })
        )}
      </div>
    </AppShell>
  );
}
