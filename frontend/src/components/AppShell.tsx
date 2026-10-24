import { useEffect, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { messagingApi } from "../api/messaging";
import { onMessagingEvent, onMessagingOpen, startMessagingSocket, stopMessagingSocket } from "../api/messagingSocket";
import { useSitePolicy } from "../api/sitePolicy";
import { useEmbedMode } from "../embed";
import { useLoginModal } from "./LoginModalProvider";
import type { Banner } from "../types/messaging";
import { useTheme } from "../theme";
import ThemeToggle from "./ThemeToggle";
import { ICONS } from "./icons";
import UserMenu from "./UserMenu";
import "./AppShell.css";

interface AppShellUser {
  id: number;
  username: string;
  email: string;
  permissions?: {
    can_review_content?: boolean;
    can_review_identity?: boolean;
    can_view_feedback?: boolean;
    can_handle_reports?: boolean;
    can_review_password_reset?: boolean;
  };
}
interface AppShellProfile {
  nickname?: string;
  avatar?: string | null;
  is_verified?: boolean;
}
interface AppShellRole {
  variant?: string;
}

const NAV: { label: string; path: string }[] = [
  { label: "主页", path: "/" },
  { label: "关于我们", path: "/about" },
  { label: "新闻", path: "/news" },
  { label: "活动", path: "/activity" },
  { label: "反馈", path: "/feedback" },
  { label: "任务", path: "/tasks" },
];

const NAV_ICONS: Record<string, ReactNode> = {
  "/": ICONS.home,
  "/about": ICONS.info,
  "/news": ICONS.news,
  "/activity": ICONS.activity,
  "/feedback": ICONS.feedback,
  "/tasks": ICONS.tasks,
};

const BANNER_TTL_MS = 24 * 60 * 60 * 1000;

function bannerStorageKey(id: number) {
  return `banner:${id}`;
}

function isBannerDismissed(id: number): boolean {
  try {
    const raw = localStorage.getItem(bannerStorageKey(id));
    if (!raw) return false;
    const t = Number(raw);
    return Number.isFinite(t) && Date.now() - t < BANNER_TTL_MS;
  } catch {
    return false;
  }
}

function dismissBanner(id: number) {
  try { localStorage.setItem(bannerStorageKey(id), String(Date.now())); } catch { /* ignore */ }
}

function formatBadge(n: number): string {
  if (n > 99) return "99+";
  return String(n);
}

export default function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [user, setUser] = useState<AppShellUser | null>(null);
  const [profile, setProfile] = useState<AppShellProfile>({});
  const [roleVariant, setRoleVariant] = useState<string>("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [inboxCount, setInboxCount] = useState(0);
  const [dmCount, setDmCount] = useState(0);
  const [notifCount, setNotifCount] = useState(0);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [showTop, setShowTop] = useState(false);
  const { openLogin, authNonce, notifyAuthChange } = useLoginModal();
  const policy = useSitePolicy();
  const embed = useEmbedMode();
  const { pref: themePref, setPref: setThemePref } = useTheme();

  useEffect(() => {
    api.me()
      .then((d: any) => {
        setUser(d.user);
        setProfile(d.profile ?? {});
        setRoleVariant(d.role?.variant ?? "");
      })
      .catch(() => { setUser(null); setRoleVariant(""); });
  }, [authNonce]);

  const showInbox = !!user && !!profile.is_verified;
  const showDm = showInbox && policy.dms_enabled;
  const showNotif = !!user;

  useEffect(() => {
    if (!showInbox) { setInboxCount(0); return; }
    api.inbox()
      .then((d: any) => setInboxCount(Number(d?.count) || 0))
      .catch(() => setInboxCount(0));
  }, [showInbox, authNonce, location.pathname]);

  useEffect(() => {
    if (!showDm) { setDmCount(0); return; }
    messagingApi.unreadCount()
      .then((d) => setDmCount(Number(d?.total) || 0))
      .catch(() => setDmCount(0));
  }, [showDm, authNonce, location.pathname]);

  useEffect(() => {
    if (!showNotif) { setNotifCount(0); return; }
    messagingApi.notificationUnreadCount()
      .then((d) => setNotifCount(Number(d?.total) || 0))
      .catch(() => setNotifCount(0));
  }, [showNotif, authNonce, location.pathname]);

  useEffect(() => {
    if (!user) {
      stopMessagingSocket();
      return;
    }
    startMessagingSocket();
    const refreshBadges = () => {
      if (showDm) {
        messagingApi.unreadCount().then((d) => setDmCount(Number(d?.total) || 0)).catch(() => {});
      }
      messagingApi.notificationUnreadCount().then((d) => setNotifCount(Number(d?.total) || 0)).catch(() => {});
    };
    const offOpen = onMessagingOpen(refreshBadges);
    // 读私信会在服务端把该会话的未读通知一并标已读（见 mark_conversation_read），
    // 所以 dm / unread 事件也要刷新通知徽标；通知落库（含聚合命中）同样两个都刷。
    const offEv = onMessagingEvent((ev) => {
      if (ev.event === "dm" || ev.event === "unread" || ev.event === "notification") {
        refreshBadges();
      }
    });
    return () => {
      offOpen();
      offEv();
    };
  }, [user, showDm]);

  useEffect(() => {
    return () => { stopMessagingSocket(); };
  }, []);

  const loadBanner = () => {
    messagingApi.currentBanner()
      .then((b) => {
        setBanner(b);
        setBannerDismissed(b ? isBannerDismissed(b.id) : false);
      })
      .catch(() => { setBanner(null); });
  };

  useEffect(() => {
    loadBanner();
  }, [location.pathname]);

  useEffect(() => {
    const onFocus = () => loadBanner();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  // 用 body.is-authed 驱动 cobalt 的 .act-guest/.act-user 显隐
  useEffect(() => {
    document.body.classList.toggle("is-authed", !!user);
    return () => { document.body.classList.remove("is-authed"); };
  }, [user]);

  useEffect(() => {
    const onScroll = () => setShowTop(window.scrollY > window.innerHeight * 0.9);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [location.pathname]);

  const go = (path: string) => {
    setDrawerOpen(false);
    if (path.startsWith("http") || path === "/admin/") window.location.href = path;
    else navigate(path);
  };
  const isActive = (p: string) =>
    p === "/" ? location.pathname === "/" : location.pathname.startsWith(p);
  const logout = async () => {
    setDrawerOpen(false);
    try { await api.logout(); } finally {
      notifyAuthChange();
      navigate("/");
    }
  };
  const showReviewQueue = !!(
    user?.permissions?.can_review_content
    || user?.permissions?.can_review_identity
    || user?.permissions?.can_view_feedback
    || user?.permissions?.can_handle_reports
    || user?.permissions?.can_review_password_reset
  );

  if (embed) {
    return <div className="cs appshell">{children}</div>;
  }

  return (
    <div className="cs appshell">
      <header className={"topnav" + (drawerOpen ? " is-open" : "")}>
        <div className="topnav-inner">
          <a className="topnav-brand" role="button" tabIndex={0} onClick={() => go("/")} aria-label="传媒社 首页">
            <img src="/static/favicon.ico" alt="传媒社社徽" width={30} height={30} />
            <span className="brand-name"><b>传媒社</b><span>南汇一中 · 2026</span></span>
          </a>
          <nav className="topnav-items" aria-label="主导航">
            {NAV.map((n) => (
              <a key={n.path} className="topnav-item" href="#"
                 aria-current={isActive(n.path) ? "page" : undefined}
                 onClick={(e) => { e.preventDefault(); go(n.path); }}>{n.label}</a>
            ))}
          </nav>
          <div className="topnav-actions">
            <ThemeToggle />
            <div className="act-guest">
              <button className="btn btn-primary btn-sm" onClick={() => openLogin()}>登录</button>
            </div>
            <div className="act-user">
              {showDm && (
                <button
                  className={"inbox-entry" + (isActive("/messages") ? " is-current" : "")}
                  type="button"
                  aria-label={dmCount > 0 ? `私信，${dmCount} 条未读` : "私信"}
                  title="私信"
                  onClick={() => go("/messages")}
                >
                  <span className="ico">{ICONS.mail}</span>
                  {dmCount > 0 && <span className="inbox-badge tnum">{formatBadge(dmCount)}</span>}
                </button>
              )}
              {showNotif && (
                <button
                  className={"inbox-entry" + (isActive("/notifications") ? " is-current" : "")}
                  type="button"
                  aria-label={notifCount > 0 ? `通知，${notifCount} 条未读` : "通知"}
                  title="通知"
                  onClick={() => go("/notifications")}
                >
                  <span className="ico">{ICONS.bell}</span>
                  {notifCount > 0 && <span className="inbox-badge tnum">{formatBadge(notifCount)}</span>}
                </button>
              )}
              {user && (
                <UserMenu
                  user={{ id: user.id, username: user.username }}
                  profile={{ nickname: profile.nickname, avatar: profile.avatar ?? null }}
                  verified={showInbox}
                  dmsEnabled={policy.dms_enabled}
                  canReview={showReviewQueue}
                  themePref={themePref}
                  onThemeSelect={setThemePref}
                  onNavigate={go}
                  onLogout={logout}
                />
              )}
            </div>
            <button className="topnav-toggle" type="button" aria-label="打开菜单"
                    aria-expanded={drawerOpen} onClick={() => setDrawerOpen((v) => !v)}>
              <span />
            </button>
          </div>
        </div>

        <div className="mobile-sheet">
          {NAV.map((n) => (
            <a key={n.path} className={isActive(n.path) ? "active" : ""} href="#"
               onClick={(e) => { e.preventDefault(); go(n.path); }}>
              <span className="ico">{NAV_ICONS[n.path]}</span>{n.label}
            </a>
          ))}
          <div className="sheet-sep" />
          {user ? (
            <>
              <button className="sheet-item" type="button" onClick={() => go("/profile")}><span className="ico">{ICONS.profile}</span>个人中心</button>
              {showDm && (
                <button className="sheet-item" type="button" onClick={() => go("/messages")}>
                  <span className="ico">{ICONS.mail}</span>私信{dmCount > 0 ? `（${dmCount}）` : ""}
                </button>
              )}
              {showNotif && (
                <button className="sheet-item" type="button" onClick={() => go("/notifications")}>
                  <span className="ico">{ICONS.bell}</span>通知{notifCount > 0 ? `（${notifCount}）` : ""}
                </button>
              )}
              {showInbox && (
                <button className="sheet-item" type="button" onClick={() => go("/inbox")}>
                  <span className="ico">{ICONS.todo}</span>待办{inboxCount > 0 ? `（${inboxCount}）` : ""}
                </button>
              )}
              <button className="sheet-item" type="button" onClick={() => go("/tasks")}><span className="ico">{ICONS.tasks}</span>任务管理</button>
              <button className="sheet-item" type="button" onClick={() => go("/activity")}><span className="ico">{ICONS.activity}</span>活动</button>
              <button className="sheet-item" type="button" onClick={() => go("/feedback")}><span className="ico">{ICONS.feedback}</span>意见反馈</button>
              {showReviewQueue && (
                <button className="sheet-item" type="button" onClick={() => go("/reviews")}><span className="ico">{ICONS.review}</span>审核队列</button>
              )}
              <button className="sheet-item" type="button" onClick={logout}><span className="ico">{ICONS.logout}</span>退出登录</button>
            </>
          ) : (
            <button className="sheet-item" type="button" onClick={() => openLogin()}><span className="ico">{ICONS.login}</span>登录</button>
          )}
        </div>
      </header>

      {/* 未认证提示（ADR-0006）：仅访客（未认证普通成员）提示。超管 / 管理员徽章
          不挡提示逻辑——他们经后台委任已是 is_verified，不会落到 visitor。 */}
      {user && roleVariant === "visitor" && (
        <button className="identity-banner" type="button" role="status"
                onClick={() => go("/profile?tab=verification")}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8h.01M11 12h1v4h1" /></svg>
          <span>          {policy.verification_enabled
            ? "你的账号尚未认证，发帖 / 发消息 / 建申报暂不可用。前往「账号认证」完成认证。"
            : "认证通道已关闭，暂无法完成认证"}</span>
        </button>
      )}

      {banner && !bannerDismissed && (
        <div className="site-banner" role="status">
          <div className="site-banner-inner">
            <span className="site-banner-body">
              {banner.link ? (
                banner.link.startsWith("http://") || banner.link.startsWith("https://") ? (
                  <a href={banner.link} target="_blank" rel="noopener noreferrer">{banner.body}</a>
                ) : (
                  <a href="#" onClick={(e) => { e.preventDefault(); go(banner.link.startsWith("/") ? banner.link : `/${banner.link}`); }}>{banner.body}</a>
                )
              ) : banner.body}
            </span>
            <button
              className="site-banner-dismiss"
              type="button"
              aria-label="关闭横幅公告"
              onClick={() => { dismissBanner(banner.id); setBannerDismissed(true); }}
            >
              ×
            </button>
          </div>
        </div>
      )}

      <main className="page">{children}</main>

      {showTop && (
        <button className="back-to-top"
          type="button"
          aria-label="回到顶部"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
        >
          <span className="ico">{ICONS.arrowUp}</span>
        </button>
      )}

      <footer className="footer">
        <div className="footer-inner">
          <div>
            <div className="footer-brand">
              <img src="/static/favicon.ico" alt="传媒社社徽" width={36} height={36} loading="lazy" />
              <b>传媒社</b>
            </div>
            <p className="footer-note">
              上海市南汇第一中学 · 传媒社<br />
              校园影像与新媒体作品策展门户<br />
              自助注册 · 信息组核审
            </p>
          </div>
          <div>
            <h5>栏目</h5>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/about"); }}>关于我们</a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/"); }}>主页</a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/news"); }}>新闻</a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/activity"); }}>活动</a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/feedback"); }}>反馈</a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/tasks"); }}>任务</a>
          </div>
          <div>
            <h5>关于</h5>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/about"); }}>关于我们</a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/join"); }}>加入社团</a>
            <a href="#" onClick={(e) => { e.preventDefault(); go("/tutorials"); }}>教程集锦</a>
          </div>
          <div>
            <h5>账户</h5>
            <a href="#" onClick={(e) => { e.preventDefault(); openLogin(); }}>登录</a>
          </div>
        </div>
        <div className="footer-bottom tnum">© 2026 上海市南汇第一中学 · 传媒社 · 信息组</div>
      </footer>
    </div>
  );
}
