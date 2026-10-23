import { useCallback, useEffect, useState } from "react";
import { announcementsApi } from "../api/announcements";
import type { Announcement } from "../types/announcements";
import {
  filterUnseenAnnouncements,
  rememberAnnouncementSeen,
} from "../utils/announcementSeen";
import AnnouncementModal from "./AnnouncementModal";
import { useLoginModal } from "./LoginModalProvider";
import "../styles/announcement.css";

/** 等其它弹窗（账号有效期 / 挤号 / 登录框）关掉再弹，避免两层遮罩叠在一起。 */
function otherModalOpen(): boolean {
  return !!document.querySelector('[aria-modal="true"]');
}

/**
 * 全站弹窗公告的全局宿主（挂在 App 根部，桌面 / 手机版共用）。
 *
 * 取数：``GET /announcements/active/`` 只返回「在线 + 在受众内 + 未读」的公告；
 * 已读由服务端台账（``AnnouncementRead``）判定，匿名访客退化为 localStorage。
 *
 * 关闭即已读：写本地记录（避免刷新又弹）+ 尽力写服务端台账（匿名 401 静默忽略）。
 * 队列里还有下一条时继续弹下一条。
 */
export default function AnnouncementHost() {
  const { authNonce } = useLoginModal();
  const [queue, setQueue] = useState<Announcement[]>([]);
  const [index, setIndex] = useState(0);
  const [ready, setReady] = useState(false);

  const load = useCallback(() => {
    announcementsApi
      .active()
      .then((data) => {
        const rows = filterUnseenAnnouncements(data.results || []);
        setQueue(rows);
        setIndex(0);
        setReady(false);
      })
      .catch(() => {
        // 公告是提示，不是功能门禁：网络失败静默。
        setQueue([]);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load, authNonce]);

  // 让位给已有弹窗：每 600ms 看一眼，最多等 15s。
  useEffect(() => {
    if (queue.length === 0) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      if (!otherModalOpen() || Date.now() - started > 15000) {
        window.clearInterval(timer);
        setReady(true);
      }
    }, 600);
    return () => window.clearInterval(timer);
  }, [queue]);

  const close = () => {
    const current = queue[index];
    if (!current) {
      setQueue([]);
      return;
    }
    rememberAnnouncementSeen(current.id);
    // 匿名调用会 401（未登录没有台账）；失败不影响体验，本地记录已拦住重复弹出。
    announcementsApi.markRead(current.id).catch(() => {});
    if (index + 1 < queue.length) {
      setIndex(index + 1);
    } else {
      setQueue([]);
      setIndex(0);
    }
  };

  if (!ready || queue.length === 0) return null;
  const current = queue[index];
  if (!current) return null;
  return <AnnouncementModal item={current} onClose={close} />;
}
