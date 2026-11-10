import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { taskApi } from "../api/tasks";
import MobilePage from "../components/MobilePage";
import type { Paginated } from "../types/pagination";
import {
  PRIORITY_COLORS,
  PRIORITY_LABELS,
  STATUS_BADGE_CLASS,
  STATUS_LABELS,
  type TaskListItem,
} from "../types/tasks";
import "../styles/mobile-work.css";

/**
 * 手机版任务列表（/#/m/tasks）。
 *
 * 数据源与桌面 /#/tasks 相同（/tasks/tasks/），保留状态筛选、优先级筛选与
 * 搜索；桌面特有的时间线 / 甘特图视图在手机上不可用（横向空间不足），
 * 列表改为「加载更多」追加。
 */

const PAGE_SIZE = 20;

export default function MobileTaskListPage() {
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [items, setItems] = useState<TaskListItem[] | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const req = useRef(0);

  // 搜索防抖：2 核小机器上逐字符打接口会把请求数放大一个量级
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const filters = useMemo(() => {
    const f: Record<string, string> = {};
    if (status) f.status = status;
    if (priority) f.priority = priority;
    if (search) f.search = search;
    return f;
  }, [status, priority, search]);

  useEffect(() => {
    const token = ++req.current;
    setLoading(true);
    taskApi
      .list({ ...filters, page: "1" })
      .then((d: Paginated<TaskListItem>) => {
        if (token !== req.current) return;
        setItems(d.results || []);
        setPage(1);
        setHasMore(!!d.next);
        setError("");
      })
      .catch((e: any) => {
        if (token !== req.current) return;
        setError(e?.message || "加载失败");
        setItems([]);
      })
      .finally(() => {
        if (token === req.current) setLoading(false);
      });
  }, [filters]);

  const loadMore = () => {
    const next = page + 1;
    const token = ++req.current;
    setLoading(true);
    taskApi
      .list({ ...filters, page: String(next) })
      .then((d: Paginated<TaskListItem>) => {
        if (token !== req.current) return;
        setItems((prev) => [...(prev || []), ...(d.results || [])]);
        setPage(next);
        setHasMore(!!d.next);
      })
      .catch((e: any) => {
        if (token === req.current) setError(e?.message || "加载失败");
      })
      .finally(() => {
        if (token === req.current) setLoading(false);
      });
  };

  const fmtDate = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString("zh-CN") : "-";

  return (
    <MobilePage title="任务" back="/m/me">
      <div className="mw-toolbar">
        <input
          className="mw-search"
          type="search"
          placeholder="搜索任务…"
          aria-label="搜索任务"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select
          className="mw-select"
          aria-label="优先级"
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
        >
          <option value="">全部优先级</option>
          {Object.entries(PRIORITY_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </div>

      <div className="mw-chips" role="tablist" aria-label="任务状态">
        <button type="button" className="mw-chip" aria-pressed={status === ""} onClick={() => setStatus("")}>
          全部
        </button>
        {Object.entries(STATUS_LABELS).map(([k, v]) => (
          <button key={k} type="button" className="mw-chip" aria-pressed={status === k} onClick={() => setStatus(k)}>
            {v}
          </button>
        ))}
      </div>

      {error && <div className="mw-alert">{error}</div>}

      {items === null && loading ? (
        <p className="mw-hint">加载中…</p>
      ) : items && items.length === 0 ? (
        <div className="mw-section">
          <p className="mw-hint" style={{ marginBottom: 0 }}>暂无任务。</p>
        </div>
      ) : (
        (items || []).map((task) => (
          <Link key={task.id} className="mw-card" to={`/m/tasks/${task.id}`}>
            <div className="mw-card-title">{task.title}</div>
            <div className="mw-card-meta">
              <span className={"badge " + STATUS_BADGE_CLASS[task.status]}>
                {STATUS_LABELS[task.status]}
              </span>
              <span className="mw-prio" style={{ color: PRIORITY_COLORS[task.priority] }}>
                {PRIORITY_LABELS[task.priority]}
              </span>
              {task.reject_reason && <span className="badge badge-warning">被打回</span>}
              <span>负责人 {task.assignee?.nickname || task.assignee?.username || "未分配"}</span>
              {task.attachment_count > 0 && <span>{task.attachment_count} 附件</span>}
              <span className="tnum">{fmtDate(task.created_at)}</span>
            </div>
            {task.tags.length > 0 && (
              <div className="mw-tags" style={{ marginTop: 8 }}>
                {task.tags.map((t) => (
                  <span key={t.id} className="tag-mini">{t.name}</span>
                ))}
              </div>
            )}
          </Link>
        ))
      )}

      {hasMore && (
        <button type="button" className="mw-more" disabled={loading} onClick={loadMore}>
          {loading ? "加载中…" : `加载更多（每页 ${PAGE_SIZE} 条）`}
        </button>
      )}
    </MobilePage>
  );
}
