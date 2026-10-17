import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import PageChrome from "../components/PageChrome";
import { api } from "../api/client";
import { tutorialApi, type TutorialItem } from "../api/tutorials";
import { useEmbedMode } from "../embed";
import AuthorReviewBanner from "../components/AuthorReviewBanner";
import ReportButton from "../components/ReportButton";
import { ICONS } from "../components/icons";
import "../styles/detail.css";

export default function TutorialDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const embed = useEmbedMode();
  const [item, setItem] = useState<TutorialItem | null>(null);
  const [error, setError] = useState("");
  const [authed, setAuthed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);

  useEffect(() => {
    if (!id) return;
    tutorialApi.get(Number(id)).then((d) => {
      setItem(d);
      document.title = `${d.title} · 教程集锦`;
    }).catch((e) => setError(e?.message || "加载失败"));
    api.me().then(() => setAuthed(true)).catch(() => setAuthed(false));
  }, [id]);

  const toggleFav = async () => {
    if (!item) return;
    setBusy(true);
    try {
      setItem(await tutorialApi.favorite(item.id));
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  if (error && !item) {
    return <PageChrome><div className="container detail-container"><div className="alert alert-danger">{error}</div></div></PageChrome>;
  }
  if (!item) {
    return <PageChrome><div className="container detail-container"><p className="empty-text">加载中…</p></div></PageChrome>;
  }

  return (
    <PageChrome>
      <div className="page-head">
        <div className="container detail-container">
          {!embed && (
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/tutorials"); }}>教程集锦</a>
            <span className="sep">/</span>
            <span>{item.title}</span>
          </nav>
          )}
          <div className="detail-head-row">
            <div>
              <h1 className="detail-title">{item.title}</h1>
              <p className="detail-sub">
                {item.uploader.nickname || item.uploader.username} · {item.views} 播放 · {item.favorite_count} 收藏
              </p>
            </div>
            {authed && (
              <div className="detail-head-actions">
                <button className="btn btn-secondary" disabled={busy} onClick={toggleFav}>
                  {item.favorited ? "已收藏" : "收藏"}
                </button>
                <ReportButton targetType="tutorial" targetId={item.id} ownerId={item.uploader.id} compact />
              </div>
            )}
          </div>
        </div>
      </div>
      {!embed && (
        <div className="container detail-container">
          <AuthorReviewBanner kind="tutorial" status={item.review_status} comment={item.review_comment} />
        </div>
      )}
      <div className="container tutorial-media">
        {item.file_type === "video" && item.file_url && !videoFailed ? (
          <video
            controls
            src={item.file_url}
            style={{ width: "100%", borderRadius: 12, background: "#000" }}
            onError={() => setVideoFailed(true)}
          >
            当前浏览器无法播放该视频，请
            <a href={item.file_url} download={item.file_name}>下载原件</a>。
          </video>
        ) : item.file_type === "video" && item.file_url && videoFailed ? (
          <p className="empty-text">当前浏览器无法解码该视频编码，请
            <a href={item.file_url} download={item.file_name}>下载原件</a> 本地播放。
          </p>
        ) : item.file_url ? (
          <p><a className="btn btn-primary" href={item.file_url} download={item.file_name}><span className="ico">{ICONS.download}</span>下载文档（{item.file_name}）</a></p>
        ) : null}
      </div>
      <div className="container detail-container">
        {item.description && <div className="card card-pad" style={{ marginTop: "var(--s-5)" }}>{item.description}</div>}
      </div>
    </PageChrome>
  );
}
