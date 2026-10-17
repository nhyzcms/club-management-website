import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLoginModal } from "../components/LoginModalProvider";
import MobileTabBar from "../components/MobileTabBar";
import { formatUnreadCount, useUnreadCounts } from "../api/unreadBadges";
import { THEME_OPTIONS, useTheme } from "../theme";
import type { RoleVariant } from "../types/profile";
import "../styles/mobile.css";

/** /auth/me/（accounts.views._profile_response）真实返回结构：
 * 身份在 role、资料在 profile，user 上仅有 id/username/email/permissions。 */
interface MeResponse {
  user: { id: number; username: string; email: string };
  role: { label: string; variant: RoleVariant };
  profile: { avatar: string | null; nickname: string; is_verified: boolean };
}

/** 列表项。badge 决定是否把未读数挂在右侧（2026-10-17：手机上原本完全看不到未读数）。 */
const ENTRIES: { to: string; label: string; badge?: "dm" | "notif" }[] = [
  { to: "/profile", label: "个人资料" },
  { to: "/tasks", label: "我的任务" },
  { to: "/messages", label: "私信", badge: "dm" },
  { to: "/notifications", label: "通知", badge: "notif" },
  { to: "/feedback", label: "意见反馈" },
];

export default function MobileMePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const { openLogin } = useLoginModal();
  const navigate = useNavigate();
  const counts = useUnreadCounts();
  const { pref: themePref, setPref: setThemePref } = useTheme();

  useEffect(() => {
    document.title = "我的 · 南汇一中传媒社";
    api
      .me()
      .then((d: any) => setMe(d))
      .catch(() => setMe(null))
      .finally(() => setLoaded(true));
  }, []);

  const user = me?.user ?? null;
  // 「进入后台管理」指向 Django admin（其门禁只认 is_staff），按身份徽章显示：
  // 管理员 / 超级管理员可见，普通用户与访客不显示。
  const isAdmin = me?.role?.variant === "admin" || me?.role?.variant === "superadmin";

  const badgeOf = (kind?: "dm" | "notif") => {
    if (!kind || !counts.signedIn) return 0;
    return kind === "dm" ? counts.dm : counts.notif;
  };

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">我的</div>
      </header>

      <section className="m-me-card">
        {user ? (
          <>
            <img className="m-me-avatar" src={me?.profile?.avatar || "/static/favicon.ico"} alt="" width={56} height={56} />
            <div>
              <div className="m-me-name">{me?.profile?.nickname || user.username}</div>
              <div className="m-me-sub">
                @{user.username} · {me?.role?.label ?? ""}
              </div>
            </div>
          </>
        ) : (
          loaded && (
            <>
              <div className="m-me-name">未登录</div>
              <button className="m-me-login" onClick={() => openLogin()}>
                登录 / 注册
              </button>
            </>
          )
        )}
      </section>

      {/* 外观（2026-10-17）：手机上原本没有主题切换入口，深色只能靠桌面端设置。
          App 壳内首次启动默认「跟随系统」（见 theme.ts 的 getTheme）。 */}
      <div className="m-list m-theme-card">
        <div className="m-theme-row">
          <span className="m-theme-label">外观</span>
          <div className="m-theme-seg" role="group" aria-label="颜色模式">
            {THEME_OPTIONS.map((o) => (
              <button
                key={o.value}
                type="button"
                className={"m-theme-btn" + (themePref === o.value ? " is-current" : "")}
                aria-pressed={themePref === o.value}
                onClick={() => setThemePref(o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="m-list">
        {ENTRIES.map((e) => {
          const badge = badgeOf(e.badge);
          return (
            <div
              key={e.to}
              role="link"
              tabIndex={0}
              className="m-list-item"
              onClick={() => navigate(e.to)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter") navigate(e.to);
              }}
            >
              <span className="m-list-label">{e.label}</span>
              {badge > 0 && <span className="m-count-badge tnum">{formatUnreadCount(badge)}</span>}
            </div>
          );
        })}
        {user && isAdmin && (
          <div
            role="link"
            tabIndex={0}
            className="m-list-item"
            onClick={() => {
              window.location.href = "/admin/";
            }}
            onKeyDown={(ev) => {
              if (ev.key === "Enter") window.location.href = "/admin/";
            }}
          >
            <span className="m-list-label">进入后台管理</span>
          </div>
        )}
        {user && (
          <button
            className="m-list-item m-list-danger"
            onClick={() => {
              api.logout().then(() => window.location.reload());
            }}
          >
            退出登录
          </button>
        )}
      </div>

      <MobileTabBar />
    </div>
  );
}
