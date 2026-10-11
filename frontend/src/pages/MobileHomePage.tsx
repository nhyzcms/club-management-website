import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { newsApi } from "../api/news";
import { activityApi } from "../api/activities";
import type { NewsListItem } from "../types/news";
import type { ActivityListItem } from "../types/activities";
import { ACTIVITY_TYPE_META, ACTIVITY_STATUS_LABELS } from "../types/activities";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/** 手机版首页（/m）：移动优先布局——顶栏 + hero + 快捷入口 + 动态卡片流 + 底部 tab。 */
export default function MobileHomePage() {
  const [news, setNews] = useState<NewsListItem[]>([]);
  const [activities, setActivities] = useState<ActivityListItem[]>([]);

  useEffect(() => {
    document.title = "南汇一中 · 传媒社";
    newsApi.list().then((d) => setNews(d.results.slice(0, 3))).catch(() => {});
    activityApi.list().then((d) => setActivities(d.results.slice(0, 3))).catch(() => {});
  }, []);

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">
          <img src="/static/favicon.ico" alt="" width={26} height={26} />
          南汇一中 · 传媒社
        </div>
        <Link className="m-topbar-user" to="/m/me">我的</Link>
      </header>

      <section className="m-hero">
        <h1>
          用镜头记录青春<br />
          <span className="accent">以创新展望未来</span>
        </h1>
        <p>校园影像与新媒体作品的策展窗口</p>
      </section>

      <div className="m-grid">
        <Link to="/activity" className="m-grid-item">
          <svg viewBox="0 0 24 24" {...stroke}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4M16 3v4M3 10h18" /></svg>
          <span>活动</span>
        </Link>
        <Link to="/news" className="m-grid-item">
          <svg viewBox="0 0 24 24" {...stroke}><path d="M4 5h13v14H4z" /><path d="M17 8h3v9a2 2 0 0 1-2 2H4" /><path d="M7 9h7M7 12h7M7 15h4" /></svg>
          <span>新闻</span>
        </Link>
        <Link to="/tutorials" className="m-grid-item">
          <svg viewBox="0 0 24 24" {...stroke}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></svg>
          <span>教程</span>
        </Link>
        <Link to="/join" className="m-grid-item">
          <svg viewBox="0 0 24 24" {...stroke}><circle cx="9" cy="8" r="4" /><path d="M2 21c0-4 3.1-6 7-6s7 2 7 6" /><path d="M19 8v6M16 11h6" /></svg>
          <span>加入</span>
        </Link>
      </div>

      <div className="m-section-h">
        <h2>最新动态</h2>
        <Link to="/news">更多</Link>
      </div>
      <div className="m-cards">
        {news.map((n) => (
          <Link key={`n${n.id}`} to={`/news/${n.id}`} className="m-card">
            {n.cover_image_url && <img className="m-card-cover" src={n.cover_image_url} alt="" width={800} height={500} loading="lazy" />}
            <div className="m-card-title">{n.title}</div>
            <div className="m-card-meta">
              <span>{n.author?.nickname || n.author?.username || "传媒社"}</span>
              <span>·</span>
              <span>{fmtDate(n.published_at || n.created_at)}</span>
            </div>
          </Link>
        ))}
        {activities.map((a) => (
          <Link key={`a${a.id}`} to={`/activity/${a.id}`} className="m-card">
            <div className="m-card-title">{a.title}</div>
            <div className="m-card-meta">
              <span className="m-badge">{ACTIVITY_TYPE_META[a.type]?.emoji} {ACTIVITY_TYPE_META[a.type]?.label}</span>
              <span>{ACTIVITY_STATUS_LABELS[a.status]}</span>
            </div>
          </Link>
        ))}
        {news.length === 0 && activities.length === 0 && (
          <p className="m-empty">暂无动态</p>
        )}
      </div>

      <MobileTabBar />
    </div>
  );
}
