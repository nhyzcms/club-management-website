import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { newsApi } from "../api/news";
import type { NewsListItem } from "../types/news";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

export default function MobileNewsPage() {
  const [items, setItems] = useState<NewsListItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    document.title = "新闻 · 南汇一中传媒社";
    newsApi
      .list()
      .then((d) => setItems(d.results))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">新闻</div>
      </header>

      <div className="m-cards" style={{ marginTop: 14 }}>
        {items.map((n) => (
          <Link key={n.id} to={`/news/${n.id}`} className="m-card">
            {n.cover_image_url && (
              <img className="m-card-cover" src={n.cover_thumbnail_url || n.cover_image_url} alt="" width={800} height={500} loading="lazy" />
            )}
            <div className="m-card-title">{n.title}</div>
            {n.summary && <p className="m-card-summary">{n.summary}</p>}
            <div className="m-card-meta">
              <span>{n.author?.nickname || n.author?.username || "—"}</span>
              <span>·</span>
              <span>{fmtDate(n.published_at || n.created_at)}</span>
              <span>·</span>
              <span>{n.views} 阅读</span>
            </div>
          </Link>
        ))}
        {loaded && items.length === 0 && <p className="m-empty">暂无新闻</p>}
      </div>

      <MobileTabBar />
    </div>
  );
}
