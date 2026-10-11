import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { activityApi } from "../api/activities";
import type { ActivityListItem } from "../types/activities";
import { ACTIVITY_TYPE_META, ACTIVITY_STATUS_LABELS } from "../types/activities";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

export default function MobileActivityPage() {
  const [items, setItems] = useState<ActivityListItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    document.title = "活动 · 南汇一中传媒社";
    activityApi
      .list()
      .then((d) => setItems(d.results))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">活动</div>
      </header>

      <div className="m-cards" style={{ marginTop: 14 }}>
        {items.map((a) => {
          const meta = ACTIVITY_TYPE_META[a.type];
          return (
            <Link key={a.id} to={`/m/activity/${a.id}`} className="m-card">
              <div className="m-card-meta" style={{ marginTop: 0, marginBottom: 8 }}>
                <span className="m-badge">
                  {meta?.emoji} {meta?.label || a.type}
                </span>
                <span>{ACTIVITY_STATUS_LABELS[a.status] || a.status}</span>
              </div>
              <div className="m-card-title">{a.title}</div>
              <div className="m-card-meta">
                <span>{a.creator?.nickname || a.creator?.username || "—"}</span>
                {a.start_at && (
                  <>
                    <span>·</span>
                    <span>{fmtDate(a.start_at)} 起</span>
                  </>
                )}
              </div>
            </Link>
          );
        })}
        {loaded && items.length === 0 && <p className="m-empty">暂无活动</p>}
      </div>

      <MobileTabBar />
    </div>
  );
}
