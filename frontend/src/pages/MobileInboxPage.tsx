import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useSitePolicy } from "../api/sitePolicy";
import MobilePage from "../components/MobilePage";
import { ACTIVITY_TYPE_META } from "../types/activities";
import { INBOX_REASON_LABELS, type InboxItem, type InboxResponse } from "../types/inbox";
import { STATUS_LABELS } from "../types/tasks";
import "../styles/mobile-work.css";

/**
 * 手机版待办（/#/m/inbox）。
 *
 * 与桌面 /#/inbox 同一数据源（/auth/inbox/），只是把条目链接改到手机版
 * 目的地：活动 → /m/activity/:id，任务 → /m/tasks/:id。
 * 未认证用户与桌面一致：引导去身份认证，而不是显示空列表。
 */

function itemTitle(item: InboxItem): string {
  if (item.kind === "activity" && item.activity) return item.activity.title;
  if (item.kind === "task" && item.task) return item.task.title;
  if (item.kind === "conversation" && item.conversation) {
    return item.conversation.title || item.conversation.last_message?.content || "未读会话";
  }
  return "待办";
}

function itemPath(item: InboxItem): string | null {
  if (item.kind === "activity" && item.activity) return `/m/activity/${item.activity.id}`;
  if (item.kind === "task" && item.task) return `/m/tasks/${item.task.id}`;
  if (item.kind === "conversation" && item.conversation) return `/messages/${item.conversation.id}`;
  return null;
}

function itemKindLabel(item: InboxItem): string {
  if (item.kind === "activity" && item.activity) return ACTIVITY_TYPE_META[item.activity.type].label;
  if (item.kind === "task") return "任务";
  return "会话";
}

export default function MobileInboxPage() {
  const policy = useSitePolicy();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [needVerify, setNeedVerify] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .me()
      .then((d: any) => {
        if (!d.profile?.is_verified) {
          setNeedVerify(true);
          setItems([]);
          return undefined;
        }
        return (api.inbox() as Promise<InboxResponse>).then((body) => setItems(body.results));
      })
      .catch((e: any) => {
        if (e?.status === 403 || e?.status === 401) {
          setNeedVerify(true);
          setItems([]);
          return;
        }
        setError(e?.message || "加载失败");
        setItems([]);
      });
  }, []);

  // 私信关闭时，会话类条目与桌面一样不展示
  const visible = items === null ? null : items.filter((i) => policy.dms_enabled || i.kind !== "conversation");

  return (
    <MobilePage title="待办" back="/m/me">
      {error && <div className="mw-alert">{error}</div>}

      {needVerify ? (
        <div className="mw-section">
          <p className="mw-hint" style={{ marginBottom: 10 }}>
            待办只对已认证用户开放。完成身份认证后即可看到待投票、待交稿、待验收等事项。
          </p>
          <Link className="mw-btn mw-btn-primary mw-btn-block" to="/profile?tab=verification">
            去身份认证
          </Link>
        </div>
      ) : visible === null ? (
        <p className="mw-hint">加载中…</p>
      ) : visible.length === 0 ? (
        <div className="mw-section">
          <p className="mw-hint" style={{ marginBottom: 0 }}>当前没有待办。</p>
        </div>
      ) : (
        <>
          <p className="mw-hint">共 {visible.length} 项需要你处理。</p>
          {visible.map((item, i) => {
            const path = itemPath(item);
            return (
              <Link key={`${item.kind}-${path || i}`} className="mw-card" to={path || "/m"}>
                <div className="mw-card-title">{itemTitle(item)}</div>
                <div className="mw-card-meta">
                  {item.pinned && <span className="badge badge-warning">即将截止</span>}
                  <span className="badge badge-brand">{INBOX_REASON_LABELS[item.reason]}</span>
                  <span>{itemKindLabel(item)}</span>
                  {item.kind === "task" && item.task && <span>{STATUS_LABELS[item.task.status]}</span>}
                  {item.end_at && (
                    <span className="tnum">截止 {new Date(item.end_at).toLocaleString("zh-CN")}</span>
                  )}
                </div>
              </Link>
            );
          })}
        </>
      )}
    </MobilePage>
  );
}
