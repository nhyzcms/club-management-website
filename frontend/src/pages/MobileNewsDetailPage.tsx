import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { newsApi } from "../api/news";
import type { NewsDetail } from "../types/news";
import ImageLightbox from "../components/ImageLightbox";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

const fmtDate = (d: string | null): string => {
  if (!d) return "";
  const dt = new Date(d);
  return `${dt.getFullYear()}年${dt.getMonth() + 1}月${dt.getDate()}日`;
};

/** 手机版新闻详情（/m/news/:id）：头图 + 标题 + 正文 + 标签 + 相关阅读。 */
export default function MobileNewsDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [news, setNews] = useState<NewsDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lightboxUrl, setLightboxUrl] = useState("");
  const proseRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError("");
    setNews(null);
    newsApi
      .get(Number(id))
      .then((d) => {
        setNews(d);
        document.title = `${d.title} · 南汇一中传媒社`;
      })
      .catch((err: { message?: string }) => setError(err.message || "加载失败"))
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

  const goBack = () => {
    const st = window.history.state as { idx?: number } | null;
    if (st && typeof st.idx === "number" && st.idx > 0) navigate(-1);
    else navigate("/m/news");
  };

  const related = news?.related ?? [];
  const cover = news?.cover_thumbnail_url || news?.cover_image_url;

  return (
    <div className="m-app">
      <header className="m-topbar">
        <button className="m-back" onClick={goBack} aria-label="返回">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
          返回
        </button>
      </header>

      {loading && <p className="m-empty">加载中…</p>}
      {!loading && !news && <p className="m-empty">{error || "新闻不存在或已下线。"}</p>}

      {!loading && news && (
        <article className="m-detail">
          <h1 className="m-detail-title">{news.title}</h1>
          <div className="m-detail-meta">
            <span>{news.author.nickname || news.author.username}</span>
            <span className="dot">·</span>
            <span>{fmtDate(news.published_at || news.created_at)}</span>
            <span className="dot">·</span>
            <span>{news.views} 阅读</span>
          </div>

          {cover && (
            <div className="m-detail-cover">
              <img src={cover} alt={news.title} onClick={() => setLightboxUrl(cover)} />
            </div>
          )}

          {news.content ? (
            <div className="m-detail-body" ref={proseRef} dangerouslySetInnerHTML={{ __html: news.content }} />
          ) : (
            <div className="m-detail-body"><p>（暂无正文）</p></div>
          )}

          {news.tags.length > 0 && (
            <div className="m-tags">
              {news.tags.map((t) => <span key={t.id} className="m-badge">{t.name}</span>)}
            </div>
          )}

          {related.length > 0 && (
            <section className="m-detail-sec">
              <h3>相关阅读</h3>
              {related.map((r) => (
                <Link key={r.id} to={`/m/news/${r.id}`} className="m-rel-item">
                  <div className="t">{r.title}</div>
                  <div className="d">{fmtDate(r.published_at || r.created_at)}</div>
                </Link>
              ))}
            </section>
          )}
        </article>
      )}

      {lightboxUrl && <ImageLightbox url={lightboxUrl} alt={news?.title || ""} onClose={() => setLightboxUrl("")} />}
      <MobileTabBar />
    </div>
  );
}
