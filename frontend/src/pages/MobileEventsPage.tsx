import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { eventApi } from "../api/events";
import { EVENT_STATUS_META, type Event } from "../types/events";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

/** 状态筛选：与桌面版 /events 的 tab 一致（草稿只有发起人/管理员能看到，服务端已过滤）。 */
const TABS: { key: string; label: string }[] = [
  { key: "", label: "全部" },
  { key: "active", label: "进行中" },
  { key: "scheduled", label: "待开始" },
  { key: "ended", label: "已结束" },
];

function fmtRange(start: string, end: string | null): string {
  const d = (iso: string | null) => {
    if (!iso) return "未设结束";
    const t = new Date(iso);
    return `${t.getMonth() + 1}/${t.getDate()} ${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  };
  return `${d(start)} — ${d(end)}`;
}

/**
 * 手机版活动列表（/m/events，events app 的「活动」，与「互动」activities 不同）。
 *
 * 桌面版是分页器 + 4 个 tab；手机屏上换成「筛选 chips + 加载更多」，
 * 不做无限滚动（3 M 带宽下滚动预取会白下流量）。
 */
export default function MobileEventsPage() {
  const [tab, setTab] = useState("");
  const [items, setItems] = useState<Event[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    async (nextPage: number, replace: boolean) => {
      setLoading(true);
      setError("");
      try {
        const params: Record<string, string> = { page: String(nextPage) };
        if (tab) params.status = tab;
        const data = await eventApi.list(params);
        setItems((prev) => (replace ? data.results : [...prev, ...data.results]));
        setPage(nextPage);
        setHasMore(Boolean(data.next));
      } catch (e: any) {
        setError(e?.message || "加载失败，请稍后重试。");
      } finally {
        setLoading(false);
        setLoaded(true);
      }
    },
    [tab],
  );

  useEffect(() => {
    document.title = "活动 · 南汇一中传媒社";
    void load(1, true);
  }, [load]);

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">活动</div>
      </header>

      <div className="m-chips" role="tablist" aria-label="活动状态">
        {TABS.map((t) => (
          <button
            key={t.key || "all"}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={"m-chip" + (tab === t.key ? " is-on" : "")}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <p className="m-empty">{error}</p>}

      <div className="m-cards" style={{ marginTop: 12 }}>
        {items.map((e) => {
          const meta = EVENT_STATUS_META[e.status];
          return (
            <Link key={e.id} to={`/m/events/${e.id}`} className="m-card">
              <div className="m-card-meta" style={{ marginTop: 0, marginBottom: 8 }}>
                <span className="m-badge">{meta?.label || e.status_label}</span>
                {e.visibility === "members" && <span>仅成员</span>}
              </div>
              <div className="m-card-title">{e.title}</div>
              <div className="m-card-meta">
                <span>{fmtRange(e.start_at, e.end_at)}</span>
              </div>
              {e.summary && <div className="m-card-summary">{e.summary}</div>}
            </Link>
          );
        })}
        {loaded && !loading && items.length === 0 && <p className="m-empty">暂无活动</p>}
        {loaded && loading && items.length === 0 && <p className="m-empty">加载中…</p>}
      </div>

      {hasMore && (
        <div className="m-actions-row" style={{ padding: "0 16px" }}>
          <button
            type="button"
            className="m-btn-ghost"
            disabled={loading}
            onClick={() => void load(page + 1, false)}
          >
            {loading ? "加载中…" : "加载更多"}
          </button>
        </div>
      )}

      <MobileTabBar />
    </div>
  );
}
