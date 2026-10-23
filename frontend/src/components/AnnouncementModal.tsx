import { useEffect } from "react";
import type { Announcement } from "../types/announcements";
import { formatPublishedAt } from "../types/announcements";
import AnnouncementDocument from "./AnnouncementDocument";

/**
 * 全站弹窗公告的弹窗本体（ADR-0042）。
 *
 * 版式：标题 + 发布时间 + 正文（可选）+ 原件（PDF / Word 保真渲染）+「我知道了」。
 * 关闭（按钮 / Esc / 点遮罩）即视为已读，由宿主 ``AnnouncementHost`` 写台账。
 */
export default function AnnouncementModal({
  item,
  onClose,
}: {
  item: Announcement;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const published = formatPublishedAt(item.published_at);

  return (
    <div className="ann-backdrop" onClick={onClose}>
      <div
        className="ann-modal"
        role="alertdialog"
        aria-modal="true"
        aria-label={item.title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ann-modal-body">
          <div className="ann-kicker">全站公告</div>
          <h2 className="ann-title">{item.title}</h2>
          {published && <div className="ann-meta tnum">发布于 {published}</div>}
          {item.summary.trim() && <p className="ann-text">{item.summary}</p>}
          <AnnouncementDocument item={item} />
        </div>
        <div className="ann-actions">
          <span className="ann-hint">关闭后可在「通知」里再次查看</span>
          <button type="button" className="btn btn-primary" onClick={onClose}>
            我知道了
          </button>
        </div>
      </div>
    </div>
  );
}
