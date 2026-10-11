import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";
import Pagination from "../components/Pagination";
import { usePagedList } from "../hooks/usePagedList";
import { api } from "../api/client";
import { tutorialApi, type TutorialItem } from "../api/tutorials";
import { REVIEW_STATUS_LABELS } from "../types/reviews";
import "../styles/list.css";
import "../styles/about.css";

const PAGE_SIZE = 20;

export default function TutorialListPage() {
  const navigate = useNavigate();
  const [mine, setMine] = useState(false);
  const [canUpload, setCanUpload] = useState(false);

  useEffect(() => {
    document.title = "教程集锦 · 南汇一中传媒社";
    api.me()
      .then((d: any) => {
        setCanUpload(!!d.profile?.is_verified);
      })
      .catch(() => setCanUpload(false));
  }, []);

  const { data, page, setPage, totalPages, loading, error } = usePagedList<TutorialItem>(
    (params) => (mine ? tutorialApi.mine(params) : tutorialApi.list(params)),
    PAGE_SIZE,
    mine ? { scope: "mine" } : {},
  );

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <span>教程集锦</span>
          </nav>
          <div className="page-head-row">
            <div>
              <h1>常用教程集锦</h1>
              <p className="section-sub">视频与文档条目。收藏 + 播放量，无弹幕 / 点赞 / 评论。</p>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {canUpload && (
                <button className="btn btn-ghost" onClick={() => setMine((v) => !v)}>
                  {mine ? "公共库" : "我的上传"}
                </button>
              )}
              {canUpload && (
                <button className="btn btn-primary" onClick={() => navigate("/tutorials/new")}>上传教程</button>
              )}
            </div>
          </div>
        </div>
      </div>
      <div className="container" style={{ paddingBottom: "var(--s-16)" }}>
        {error && <div className="alert alert-danger">{error}</div>}
        {loading ? <p className="task-empty">加载中…</p> : data.length === 0 ? (
          <p className="task-empty">暂无教程。</p>
        ) : (
          <div className="tgrid">
            {data.map((item) => (
              <article key={item.id} className="tcard" onClick={() => navigate(`/tutorials/${item.id}`)}>
                <div className="tcard-cover">
                  {item.cover_url ? <img src={item.cover_url} alt="" width={800} height={500} loading="lazy" /> : (item.file_type === "video" ? "▶" : "📄")}
                </div>
                <div className="tcard-body">
                  <h3>{item.title}</h3>
                  {item.review_status && item.review_status !== "approved" && (
                    <div className="tcard-tags">
                      <span className="badge">
                        {REVIEW_STATUS_LABELS[item.review_status] ?? item.review_status}
                      </span>
                    </div>
                  )}
                  <div className="tcard-foot">
                    <span>{item.views} 播放</span>
                    <span>{item.favorite_count} 收藏</span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
        {!loading && <Pagination page={page} totalPages={totalPages} onChange={setPage} />}
      </div>
    </AppShell>
  );
}
