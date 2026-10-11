import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tutorialApi, type TutorialItem } from "../api/tutorials";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

/** 手机版教程集锦（/m/tutorials）：视频与文档条目列表。 */
export default function MobileTutorialsPage() {
  const [items, setItems] = useState<TutorialItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    document.title = "教程集锦 · 南汇一中传媒社";
    tutorialApi
      .list()
      .then((d) => setItems(d.results))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">教程集锦</div>
      </header>

      <div className="m-cards" style={{ marginTop: 14 }}>
        {items.map((t) => (
          <Link key={t.id} to={`/m/tutorials/${t.id}`} className="m-card">
            {t.cover_url ? (
              <img className="m-card-cover" src={t.cover_url} alt="" width={800} height={500} loading="lazy" />
            ) : (
              <div className="m-card-cover-ph">{t.file_type === "video" ? "▶" : "📄"}</div>
            )}
            <div className="m-card-title">{t.title}</div>
            <div className="m-card-meta">
              <span>{t.file_type === "video" ? "视频" : "文档"}</span>
              <span>·</span>
              <span>{t.views} 播放</span>
              <span>·</span>
              <span>{t.favorite_count} 收藏</span>
            </div>
          </Link>
        ))}
        {loaded && items.length === 0 && <p className="m-empty">暂无教程</p>}
      </div>

      <MobileTabBar />
    </div>
  );
}
