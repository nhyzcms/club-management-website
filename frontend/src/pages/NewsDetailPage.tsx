import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import Avatar from "../components/Avatar";
import ArticleToc, { htmlWithHeadingIds } from "../components/ArticleToc";
import ImageLightbox from "../components/ImageLightbox";
import PageChrome from "../components/PageChrome";
import { api } from "../api/client";
import { newsApi } from "../api/news";
import { type NewsDetail } from "../types/news";
import { useEmbedMode } from "../embed";
import AuthorReviewBanner from "../components/AuthorReviewBanner";
import CommentSection from "../components/CommentSection";
import ReportButton from "../components/ReportButton";
import "../styles/news.css";
import "../styles/form.css";

const fmtDate = (d: string | null) => {
  if (!d) return "—";
  const dt = new Date(d);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${dt.getFullYear()}.${p(dt.getMonth() + 1)}.${p(dt.getDate())}`;
};

const fmtDateTime = (d: string | null) => {
  if (!d) return "";
  const dt = new Date(d);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${fmtDate(d)} ${p(dt.getHours())}:${p(dt.getMinutes())}`;
};

export default function NewsDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const embed = useEmbedMode();
  const [news, setNews] = useState<NewsDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState("");
  const [canEdit, setCanEdit] = useState(false);
  const proseRef = useRef<HTMLDivElement>(null);

  // 信息组：前台编辑入口（匿名 / 普通用户静默）
  useEffect(() => {
    api.me()
      .then((d: any) => setCanEdit(!!d.user?.permissions?.can_manage_news))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    newsApi.get(Number(id))
      .then(setNews)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  // 正文图片点击 → 大图查看（事件委托：正文 HTML 不能直接挂 React onClick）
  useEffect(() => {
    const el = proseRef.current;
    if (!el) return;
    const onClick = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "IMG") {
        e.preventDefault();
        const img = t as HTMLImageElement;
        if (img.src) setLightboxUrl(img.src);
      }
    };
    el.addEventListener("click", onClick);
    return () => el.removeEventListener("click", onClick);
  }, [news]);

  const copyLink = async () => {
    try { await navigator.clipboard.writeText(window.location.href); } catch { /* ignore */ }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  if (loading) return <PageChrome><div className="container"><p className="news-empty">加载中…</p></div></PageChrome>;
  if (error && !news) return <PageChrome><div className="container"><p className="news-empty">{error}</p></div></PageChrome>;
  if (!news) return <PageChrome><div className="container"><p className="news-empty">新闻不存在或已下线。</p></div></PageChrome>;

  const related = news.related || [];
  const prepared = htmlWithHeadingIds(news.content || "");

  return (
    <PageChrome>
      <div className="container">
        <div className="detail-layout">
          <article className="article">
            {!embed && (
            <nav className="breadcrumb" style={{ marginTop: "var(--s-8)" }}>
              <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
              <span className="sep">/</span>
              <a href="#" onClick={(e) => { e.preventDefault(); navigate("/news"); }}>新闻</a>
              <span className="sep">/</span>
              <span>{news.title}</span>
            </nav>
            )}

            {!embed && (
            <AuthorReviewBanner
              kind="news"
              status={news.review_status}
              comment={news.review_comment}
            />
            )}
            {!embed && canEdit && news.draft_saved_at && (
              <div className="alert alert-info compose-notice" style={{ marginTop: "var(--s-4)" }}>
                <span>公开页显示的是已发布版本；还有一条未发布的修改（{fmtDateTime(news.draft_saved_at)} 保存）。</span>
                <button type="button" className="alert-link" onClick={() => navigate(`/news/${news.id}/edit`)}>继续编辑</button>
              </div>
            )}
            <h1>{news.title}</h1>

            <div className="article-meta">
              <span className="author">
                <Link to={`/u/${news.author.id}`}><Avatar user={news.author} size="sm" /></Link>
                {news.author.nickname || news.author.username}
              </span>
              <span className="sep">·</span>
              <span className="date tnum">{fmtDate(news.published_at || news.created_at)}</span>
              <span className="sep">·</span>
              <span>阅读 {news.views}</span>
              <span className="sep">·</span>
              <span>来源：传媒社</span>
            </div>

            <div className={"article-hero" + (news.cover_image_url ? "" : " ph-img")}>
              {news.cover_image_url ? (
                <img src={news.cover_image_url} alt={news.title}
                     width={800} height={500} fetchPriority="high"
                     onClick={() => setLightboxUrl(news.cover_image_url || "")} />
              ) : (
                <>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round"><path d="M4 8h3l2-2h6l2 2h3v11H4z" /><circle cx="12" cy="13" r="3.2" /></svg>
                  <span className="ph-label">头图 · 待补充</span>
                </>
              )}
            </div>

            {news.content ? (
              <div className="prose" ref={proseRef} dangerouslySetInnerHTML={{ __html: prepared.html }} />
            ) : (
              <div className="prose"><p className="lead">（暂无正文）</p></div>
            )}

            {news.tags.length > 0 && (
              <div className="article-tags">
                {news.tags.map((t) => <span key={t.id} className="chip">{t.name}</span>)}
              </div>
            )}

            {!embed && (
            <div className="article-actions">
              {canEdit && (
                <button className="btn btn-primary" onClick={() => navigate(`/news/${news.id}/edit`)}>
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" /></svg> 编辑
                </button>
              )}
              <button className="btn btn-secondary" onClick={() => navigate("/news")}>
                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M11 6l-6 6 6 6" /></svg> 返回列表
              </button>
              <button className="btn btn-ghost" onClick={copyLink}>
                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a4 4 0 0 0 5.7.4l3-3a4 4 0 0 0-5.7-5.7l-1.4 1.4" /><path d="M14 11a4 4 0 0 0-5.7-.4l-3 3a4 4 0 0 0 5.7 5.7l1.4-1.4" /></svg> {copied ? "已复制" : "复制链接"}
              </button>
              <ReportButton targetType="news" targetId={news.id} ownerId={news.author.id} compact />
            </div>
            )}

            <div className="author-card">
              <Link to={`/u/${news.author.id}`}><Avatar user={news.author} size="md" /></Link>
              <div>
                <div className="ac-name">{news.author.nickname || news.author.username}</div>
                <div className="ac-desc">@{news.author.username} · 本内容由信息组发布。</div>
              </div>
            </div>
          </article>

          <aside className="detail-side">
            <ArticleToc html={news.content || ""} />
            <div className="side-card">
              <h4><span className="bar" /> 文章信息</h4>
              <div className="meta-row"><span className="k">发布</span><span className="v tnum">{fmtDate(news.published_at || news.created_at)}</span></div>
              <div className="meta-row"><span className="k">来源</span><span className="v">传媒社</span></div>
              <div className="meta-row"><span className="k">阅读</span><span className="v">{news.views}</span></div>
            </div>
            {!embed && related.length > 0 && (
              <div className="side-card">
                <h4><span className="bar" /> 相关阅读</h4>
                {related.map((r) => (
                  <a key={r.id} className="rel-item" href="#"
                     onClick={(e) => { e.preventDefault(); navigate(`/news/${r.id}`); }}>
                    <h5>{r.title}</h5>
                    <span className="rdate">{fmtDate(r.published_at || r.created_at)}</span>
                  </a>
                ))}
              </div>
            )}
          </aside>
        </div>

        <CommentSection host={{ news: news.id }} />

        {lightboxUrl && (
          <ImageLightbox url={lightboxUrl} alt={news.title} onClose={() => setLightboxUrl("")} />
        )}

        {!embed && related.length > 0 && (
          <section style={{ paddingBottom: "var(--s-16)" }}>
            <div className="section-head">
              <div>
                <div className="eyebrow">MORE · 继续阅读</div>
                <h2 className="section-title"><span className="bar" /> 相关推荐</h2>
              </div>
            </div>
            <div className="related-grid">
              {related.map((r) => (
                <a key={r.id} className="card card-hover" href="#"
                   onClick={(e) => { e.preventDefault(); navigate(`/news/${r.id}`); }}>
                  <div className={"card-media" + (r.cover_image_url ? "" : " ph-img")}>
                    {r.cover_image_url ? (
                      <img src={r.cover_thumbnail_url || r.cover_image_url} alt={r.title} width={800} height={450} loading="lazy" />
                    ) : (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="8" /><path d="M4 12h16" /></svg>
                    )}
                  </div>
                  <div className="card-body">
                    <span className="date tnum">{fmtDate(r.published_at || r.created_at)}</span>
                    <h3 style={{ marginTop: "10px" }}>{r.title}</h3>
                  </div>
                </a>
              ))}
            </div>
          </section>
        )}
      </div>
    </PageChrome>
  );
}
