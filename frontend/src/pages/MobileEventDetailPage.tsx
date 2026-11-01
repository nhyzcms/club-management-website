import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { eventApi } from "../api/events";
import { EVENT_STATUS_META, type Event } from "../types/events";
import MobilePage from "../components/MobilePage";
import "../styles/mobile.css";

function fmtRange(start: string, end: string | null): string {
  const d = (iso: string | null) => {
    if (!iso) return "未设结束";
    const t = new Date(iso);
    return `${t.getMonth() + 1}/${t.getDate()} ${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  };
  return `${d(start)} — ${d(end)}`;
}

/**
 * 手机版活动详情（/m/events/:id）。
 *
 * 业务判定与桌面版 EventDetailPage 保持一致：能看到「发布 / 归档 / 删除草稿」
 * 的只有组织者、持有 can_manage_events 能力的人、超级管理员。
 */
export default function MobileEventDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [event, setEvent] = useState<Event | null>(null);
  const [me, setMe] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    eventApi
      .get(Number(id))
      .then(setEvent)
      .catch((e: any) => setError(e?.message || "活动不存在或不可见"));
  }, [id]);

  useEffect(() => {
    load();
    api.me().then(setMe).catch(() => setMe(null));
  }, [load]);

  const canManage = !!me && !!event && (
    me.user?.id === event.organizer?.id ||
    me.user?.permissions?.can_manage_events === true ||
    me.role?.variant === "superadmin"
  );

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
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
      navigate("/m/events", { replace: true });
    } catch (e: any) {
      setError(e?.message || "删除失败");
    } finally {
      setBusy(false);
    }
  }

  const meta = event ? EVENT_STATUS_META[event.status] : null;

  return (
    <MobilePage title="活动" back="/m/events">
      <div>
        {!event ? (
          <p className="m-empty">{error || "加载中…"}</p>
        ) : (
          <>
            <div className="m-detail-medals">
              <span className="m-badge">{meta?.label || event.status_label}</span>
              {event.visibility === "members" && <span className="m-badge">仅成员</span>}
            </div>
            <h1 className="m-detail-title">{event.title}</h1>
            <div className="m-detail-meta">
              <span>{fmtRange(event.start_at, event.end_at)}</span>
              {event.organizer && (
                <>
                  <span className="dot">·</span>
                  <span>{event.organizer.nickname || event.organizer.username}</span>
                </>
              )}
            </div>

            {error && <p className="m-hint" style={{ color: "var(--danger, #c0392b)" }}>{error}</p>}

            {event.summary && <p className="m-hint">{event.summary}</p>}

            {event.body ? (
              <div className="m-detail-body" dangerouslySetInnerHTML={{ __html: event.body }} />
            ) : (
              <p className="m-empty">这个活动还没有正文。</p>
            )}

            <section className="m-detail-sec">
              <h3>参与方式</h3>
              <p className="m-hint">
                {event.module_key
                  ? `${event.module_key}（该形态尚未接入）`
                  : "该活动为展示型，没有额外的参与流程。"}
              </p>
            </section>

            {canManage && (
              <div className="m-actions-row">
                {event.status === "draft" && (
                  <button
                    className="m-btn-primary"
                    disabled={busy}
                    onClick={() => void act(() => eventApi.publish(event.id))}
                  >
                    发布
                  </button>
                )}
                {event.status === "ended" && (
                  <button
                    className="m-btn-ghost"
                    disabled={busy}
                    onClick={() => void act(() => eventApi.archive(event.id))}
                  >
                    归档
                  </button>
                )}
                {event.status === "draft" && (
                  <button
                    className="m-btn-ghost"
                    style={{ color: "var(--danger, #c0392b)" }}
                    disabled={busy}
                    onClick={() => void remove()}
                  >
                    删除草稿
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </MobilePage>
  );
}
