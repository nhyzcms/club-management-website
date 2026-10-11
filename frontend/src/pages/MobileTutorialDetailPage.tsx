import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { tutorialApi, type TutorialItem } from "../api/tutorials";
import MobileTabBar from "../components/MobileTabBar";
import "../styles/mobile.css";

/** 手机版教程详情（/m/tutorials/:id）：视频播放 / 文档下载 + 收藏。 */
export default function MobileTutorialDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [item, setItem] = useState<TutorialItem | null>(null);
  const [error, setError] = useState("");
  const [authed, setAuthed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);

  useEffect(() => {
    if (!id) return;
    tutorialApi
      .get(Number(id))
      .then((d) => {
        setItem(d);
        document.title = `${d.title} · 教程集锦`;
      })
      .catch((e: { message?: string }) => setError(e?.message || "加载失败"));
    api.me().then(() => setAuthed(true)).catch(() => setAuthed(false));
  }, [id]);

  const toggleFav = async () => {
    if (!item) return;
    setBusy(true);
    try {
      setItem(await tutorialApi.favorite(item.id));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const goBack = () => {
    const st = window.history.state as { idx?: number } | null;
    if (st && typeof st.idx === "number" && st.idx > 0) navigate(-1);
    else navigate("/m/tutorials");
  };

  return (
    <div className="m-app">
      <header className="m-topbar">
        <button className="m-back" onClick={goBack} aria-label="返回">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
          返回
        </button>
      </header>

      {!item && !error && <p className="m-empty">加载中…</p>}
      {!item && error && <p className="m-empty">{error}</p>}

      {item && (
        <article className="m-detail">
          <h1 className="m-detail-title">{item.title}</h1>
          <div className="m-detail-meta">
            <span>{item.uploader.nickname || item.uploader.username}</span>
            <span className="dot">·</span>
            <span>{item.views} 播放</span>
            <span className="dot">·</span>
            <span>{item.favorite_count} 收藏</span>
          </div>

          {authed && (
            <div className="m-actions-row">
              <button className="m-btn-ghost" disabled={busy} onClick={toggleFav}>
                {item.favorited ? "已收藏" : "收藏"}
              </button>
            </div>
          )}

          <section className="m-detail-sec">
            <h3>内容</h3>
            {item.file_type === "video" && item.file_url && !videoFailed ? (
              <video
                controls
                playsInline
                preload="metadata"
                src={item.file_url}
                className="m-video"
                onError={() => setVideoFailed(true)}
              >
                当前浏览器无法播放该视频，请
                <a href={item.file_url} download={item.file_name}>下载原件</a>。
              </video>
            ) : item.file_type === "video" && item.file_url ? (
              <p className="m-hint" style={{ marginBottom: 0 }}>
                当前浏览器无法解码该视频编码，请
                <a href={item.file_url} download={item.file_name}>下载原件</a> 本地播放。
              </p>
            ) : item.file_url ? (
              <a className="m-btn-primary" href={item.file_url} download={item.file_name}>
                下载文档（{item.file_name}）
              </a>
            ) : (
              <p className="m-hint" style={{ marginBottom: 0 }}>文件暂不可用。</p>
            )}
          </section>

          {item.description && (
            <div className="m-detail-body">
              <p style={{ whiteSpace: "pre-wrap" }}>{item.description}</p>
            </div>
          )}

          {error && <div className="alert alert-danger" style={{ marginTop: 14 }}><span>{error}</span></div>}
        </article>
      )}

      <MobileTabBar />
    </div>
  );
}
