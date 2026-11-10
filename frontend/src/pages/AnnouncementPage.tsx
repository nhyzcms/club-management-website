import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { announcementsApi } from "../api/announcements";
import AnnouncementDocument from "../components/AnnouncementDocument";
import AppShell from "../components/AppShell";
import MobilePage from "../components/MobilePage";
import type { Announcement } from "../types/announcements";
import { formatPublishedAt } from "../types/announcements";
import { isMobileDevice } from "../utils/device";
import { rememberAnnouncementSeen } from "../utils/announcementSeen";
import "../styles/announcement.css";

/**
 * 公告详情 ``/#/announcements/:id``（ADR-0042）。
 *
 * 站内通知点进来就是这里——弹窗关掉之后，接收者仍能在系统消息里回看同一条公告，
 * 原件（PDF / Word）也照原排版渲染。桌面走 AppShell，手机走 MobilePage。
 */
export default function AnnouncementPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [item, setItem] = useState<Announcement | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const numeric = Number(id);
    if (!Number.isFinite(numeric)) {
      setError("公告不存在");
      return;
    }
    setError("");
    announcementsApi
      .get(numeric)
      .then((data) => {
        setItem(data);
        document.title = `${data.title} · 全站公告 · 南汇一中传媒社`;
        // 打开详情即视为已读（匿名 401 静默忽略）；本地也记一份，避免弹窗再弹。
        rememberAnnouncementSeen(data.id);
        announcementsApi.markRead(data.id).catch(() => {});
      })
      .catch((e: any) => {
        setError(e?.kind === "not_found" ? "公告不存在或已下线。" : (e?.message || "加载失败"));
      });
  }, [id]);

  const body = (
    <div className="container" style={{ paddingTop: "var(--s-6)", paddingBottom: "var(--s-16)" }}>
      {error && <div className="alert alert-danger">{error}</div>}
      {!error && !item && <p className="muted">加载中…</p>}
      {item && (
        <article className="ann-page detail-section">
          <div className="ann-kicker">全站公告</div>
          <h1 className="ann-title">{item.title}</h1>
          <div className="ann-meta tnum">
            发布于 {formatPublishedAt(item.published_at)}
            {item.audience !== "all" && ` · 仅${item.audience_label}可见`}
          </div>
          {item.summary.trim() && <p className="ann-text">{item.summary}</p>}
          <AnnouncementDocument item={item} />
        </article>
      )}
    </div>
  );

  if (isMobileDevice()) {
    return (
      <MobilePage title="全站公告" back={() => navigate(-1)}>
        {body}
      </MobilePage>
    );
  }

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); }}>主页</a>
            <span className="sep">/</span>
            <a href="#" onClick={(e) => { e.preventDefault(); navigate("/notifications"); }}>通知</a>
            <span className="sep">/</span>
            <span>全站公告</span>
          </nav>
        </div>
      </div>
      {body}
    </AppShell>
  );
}
