import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { ContentType, ContentItem } from "../../types/profile";
import { ACTIVITY_TYPE_LABELS, type ActivityType } from "../../types/activities";
import "../../styles/form.css";

const DETAIL_PATH: Record<ContentType, string> = {
  news: "/news",
  feedback: "/feedback",
  tasks: "/tasks",
  activities: "/activity",
  tutorials: "/tutorials",
};

const FEEDBACK_STATUS: Record<string, string> = {
  pending: "待处理", closed: "已了结",
};
const FEEDBACK_CATEGORY: Record<string, string> = {
  suggestion: "建议", complaint: "投诉", other: "其他",
};
const TASK_STATUS: Record<string, string> = {
  pending: "待处理", in_progress: "进行中", reviewing: "待验收", review: "审核中", completed: "已完成", cancelled: "已取消",
};
const TASK_PRIORITY: Record<string, string> = {
  low: "低", medium: "中", high: "高", urgent: "紧急",
};

function reviewMeta(it: ContentItem): string {
  return it.review_status === "pending" ? " · 待审"
    : it.review_status === "rejected" ? " · 已驳回"
    : it.review_status === "removed" ? " · 已下架"
    : "";
}

function metaFor(type: ContentType, it: ContentItem): string {
  if (type === "news") {
    const draft = it.is_published === false ? " · 草稿" : "";
    return (it.published_at?.slice(0, 10) || "") + draft + reviewMeta(it);
  }
  if (type === "feedback") {
    const cat = it.category ? FEEDBACK_CATEGORY[it.category] ?? it.category : "";
    const st = it.status ? FEEDBACK_STATUS[it.status] ?? it.status : "";
    return [cat, st, it.created_at?.slice(0, 10)].filter(Boolean).join(" · ");
  }
  if (type === "activities") {
    const kind = it.type ? ACTIVITY_TYPE_LABELS[it.type as ActivityType] ?? it.type : "";
    return [kind, it.created_at?.slice(0, 10)].filter(Boolean).join(" · ") + reviewMeta(it);
  }
  if (type === "tutorials") {
    return (it.created_at?.slice(0, 10) || "") + reviewMeta(it);
  }
  const st = it.status ? TASK_STATUS[it.status] ?? it.status : "";
  const pr = it.priority ? TASK_PRIORITY[it.priority] ?? it.priority : "";
  return [st, pr, it.created_at?.slice(0, 10)].filter(Boolean).join(" · ");
}

interface Props {
  userId: number;
  type: ContentType;
  selfView: boolean;
}

export default function ContentListPanel({ userId, type }: Props) {
  const [items, setItems] = useState<ContentItem[] | null>(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    setItems(null);
    setError("");
    setPage(1);
    setHasMore(false);
    api.getUserContent(userId, type, 1)
      .then((d: any) => {
        setItems(d.results as ContentItem[]);
        setHasMore(d.next != null);
      })
      .catch((e: any) => setError(e.status === 403 ? "无权查看" : "加载失败"));
  }, [userId, type]);

  const loadMore = async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const d: any = await api.getUserContent(userId, type, page + 1);
      setItems((prev) => [...(prev || []), ...(d.results as ContentItem[])]);
      setPage((p) => p + 1);
      setHasMore(d.next != null);
    } catch {
      setError("加载失败");
    } finally {
      setLoadingMore(false);
    }
  };

  if (error) return <p className="muted">{error}</p>;
  if (items === null) return <p className="muted">加载中…</p>;
  if (items.length === 0) return <p className="muted">暂无内容</p>;

  const go = (id: number) => navigate(`${DETAIL_PATH[type]}/${id}`);

  return (
    <>
      <ul className="profile-content-list">
        {items.map((it) => (
          <li
            key={it.id}
            className="profile-content-item"
            role="button"
            tabIndex={0}
            onClick={() => go(it.id)}
            onKeyDown={(e) => { if (e.key === "Enter") go(it.id); }}
          >
            <div className="pci-title">{it.title}</div>
            <div className="pci-meta">{metaFor(type, it)}</div>
          </li>
        ))}
      </ul>
      {hasMore && (
        <button className="profile-load-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "加载中…" : "加载更多"}
        </button>
      )}
    </>
  );
}
