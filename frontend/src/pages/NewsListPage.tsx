import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import Pagination from "../components/Pagination";
import { usePagedList } from "../hooks/usePagedList";
import { api } from "../api/client";
import { newsApi } from "../api/news";
import {
  type NewsListItem,
  type NewsTag,
  NEWS_PAGE_SIZE,
} from "../types/news";
import { REVIEW_STATUS_LABELS } from "../types/reviews";
import "../styles/news.css";

const fmtDate = (d: string | null) => {
  if (!d) return "";
  const dt = new Date(d);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${dt.getFullYear()}.${p(dt.getMonth() + 1)}.${p(dt.getDate())}`;
};

interface Me { can_manage_news?: boolean; can_review_content?: boolean; can_review_identity?: boolean }

export default function NewsListPage() {
  const navigate = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [featured, setFeatured] = useState<NewsListItem | null>(null);
  const [hot, setHot] = useState<NewsListItem[]>([]);
  const [tagCloud, setTagCloud] = useState<NewsTag[]>([]);
  const [search, setSearch] = useState("");
  const [mine, setMine] = useState(false);

  // 公开页：匿名也可读，故 me() 失败静默（不弹登录）
  useEffect(() => {
    api.me().then((d: any) => setMe({
      can_manage_news: d.user?.permissions?.can_manage_news,
      can_review_content: d.user?.permissions?.can_review_content,
      can_review_identity: d.user?.permissions?.can_review_identity,
    })).catch(() => {});
  }, []);

  useEffect(() => {
    newsApi.featured().then(setFeatured).catch(() => {});
    newsApi.hot().then(setHot).catch(() => {});
    newsApi.tags().then(setTagCloud).catch(() => {});
  }, []);

  const {
    data: items,
    page,
    setPage,
    totalPages,
    loading,
  } = usePagedList<NewsListItem>(
    (params) => {
      const next = { ...params };
      const isMine = next.mine === "1";
      delete next.mine;
      return isMine ? newsApi.mine(next) : newsApi.list(next);
    },
    NEWS_PAGE_SIZE,
    { search: search || undefined, mine: mine ? "1" : undefined },
  );

  const showFeatured = !mine && !search && page === 1;
  // 头条同时在列表中出现会重复，hero 展示时从列表中剔除
  const visibleItems = showFeatured && featured ? items.filter((n) => n.id !== featured.id) : items;

  const onSearch = (v: string) => setSearch(v);

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>新闻</span>
          </nav>
          <div className="page-head-row">
            <div>
              <h1>新闻</h1>
              <p className="section-sub">社团公告、回顾与通知。</p>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(me?.can_review_content || me?.can_review_identity) && (
              <button className="btn btn-ghost" onClick={() => navigate("/reviews")}>审核队列</button>
            )}
            {me?.can_manage_news && (
              <button className="btn btn-ghost" onClick={() => setMine((v) => !v)}>
                {mine ? "公开列表" : "我的稿件"}
              </button>
            )}
            {me?.can_manage_news && (
              <button className="btn btn-primary" onClick={() => navigate("/news/new")}>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
                写新闻
              </button>
            )}
            </div>
          </div>
        </div>
      </div>

      <div className="container">
        <div className="news-layout">
          <div>
            {/* 头条：仅在未筛选首页展示 */}
            {showFeatured && featured && (
              <a className="feature" href="#"
                 onClick={(e) => { e.preventDefault(); navigate(`/news/${featured.id}`); }}>
                <div className={"feature-media" + (featured.cover_image_url ? "" : " ph-img")}>
                  {featured.cover_image_url ? (
                    <img src={featured.cover_thumbnail_url || featured.cover_image_url} alt={featured.title} width={800} height={500} />
                  ) : (
                    <>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"><path d="M4 8h3l2-2h6l2 2h3v11H4z" /><circle cx="12" cy="13" r="3.2" /></svg>
                      <span className="ph-label">头条配图</span>
                    </>
                  )}
                </div>
                <div className="feature-body">
                  <span className="badge badge-brand feature-tag"><span className="badge-dot" />头条</span>
                  <h2>{featured.title}</h2>
                  <p>{featured.summary}</p>
                  <div className="feature-meta">
                    <span className="date tnum">{fmtDate(featured.published_at || featured.created_at)}</span>
                    <span>· {featured.author.nickname || featured.author.username}</span>
                    <span>· 阅读 {featured.views}</span>
                  </div>
                </div>
              </a>
            )}

            {/* 列表 */}
            {loading ? (
              <p className="news-empty">加载中…</p>
            ) : visibleItems.length === 0 ? (
              <p className="news-empty">{search ? "该筛选下暂无内容。" : "暂无新闻。"}</p>
            ) : (
              visibleItems.map((n) => (
                <a key={n.id} className="news-item" href="#"
                   onClick={(e) => { e.preventDefault(); navigate(`/news/${n.id}`); }}>
                  <div className={"thumb" + (n.cover_image_url ? "" : " ph-img")}>
                    {n.cover_image_url ? (
                      <img src={n.cover_thumbnail_url || n.cover_image_url} alt={n.title} width={800} height={500} loading="lazy" />
                    ) : (
                      <>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16v12H4z" /><path d="M4 6h16M9 10h6" /></svg>
                        <span className="ph-label">配图</span>
                      </>
                    )}
                  </div>
                  <div>
                    <div className="meta">
                      <span className="date tnum">{fmtDate(n.published_at || n.created_at)}</span>
                    </div>
                    <h3>{n.title}</h3>
                    <p>{n.summary}</p>
                    <span className="read">阅读 {n.views}</span>
                    {mine && n.draft_saved_at && (
                      <span className="badge badge-brand" style={{ marginLeft: 8 }}>待发布修改</span>
                    )}
                    {mine && n.review_status && n.review_status !== "approved" && (
                      <span className="badge" style={{ marginLeft: 8 }}>
                        {REVIEW_STATUS_LABELS[n.review_status] ?? n.review_status}
                      </span>
                    )}
                  </div>
                </a>
              ))
            )}

            {/* 分页 */}
            {!loading && <Pagination page={page} totalPages={totalPages} onChange={setPage} />}
          </div>

          {/* 侧栏 */}
          <aside className="side">
            <div className="side-card">
              <div className="input-affix">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>
                <input className="input" type="search" placeholder="搜索新闻…" aria-label="搜索新闻"
                       value={search} onChange={(e) => onSearch(e.target.value)} />
              </div>
            </div>
            <div className="side-card">
              <h4><span className="bar" /> 热门阅读</h4>
              <ul className="hot-list">
                {hot.length === 0 ? (
                  <li><span className="rank">·</span><div><span style={{ color: "var(--faint)", fontSize: 13 }}>暂无数据</span></div></li>
                ) : hot.map((n, i) => (
                  <li key={n.id}>
                    <span className="rank">{String(i + 1).padStart(2, "0")}</span>
                    <div>
                      <a href="#" onClick={(e) => { e.preventDefault(); navigate(`/news/${n.id}`); }}>{n.title}</a>
                      <div className="hv">阅读 {n.views}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
            <div className="side-card">
              <h4><span className="bar" /> 标签</h4>
              <div className="tag-cloud">
                {tagCloud.length === 0 ? (
                  <span className="chip">暂无标签</span>
                ) : tagCloud.map((t) => (
                  <span key={t.id} className="chip">{t.name}{typeof t.news_count === "number" ? ` · ${t.news_count}` : ""}</span>
                ))}
              </div>
            </div>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}
