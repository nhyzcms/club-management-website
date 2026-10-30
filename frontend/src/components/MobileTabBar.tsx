import { NavLink } from "react-router-dom";
import { formatUnreadCount, useUnreadCounts } from "../api/unreadBadges";

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

const TABS = [
  {
    to: "/m",
    label: "首页",
    icon: (
      <svg viewBox="0 0 24 24" {...stroke}>
        <path d="M3 10.5 12 3l9 7.5" />
        <path d="M5 9.5V21h14V9.5" />
      </svg>
    ),
  },
  {
    to: "/m/activity",
    label: "互动",
    icon: (
      <svg viewBox="0 0 24 24" {...stroke}>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M8 3v4M16 3v4M3 10h18" />
      </svg>
    ),
  },
  {
    to: "/m/news",
    label: "新闻",
    icon: (
      <svg viewBox="0 0 24 24" {...stroke}>
        <path d="M4 5h13v14H4z" />
        <path d="M17 8h3v9a2 2 0 0 1-2 2H4" />
        <path d="M7 9h7M7 12h7M7 15h4" />
      </svg>
    ),
  },
  {
    to: "/m/me",
    label: "我的",
    icon: (
      <svg viewBox="0 0 24 24" {...stroke}>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" />
      </svg>
    ),
  },
];

/**
 * 手机版底部 tab 栏（固定在视口底部，含安全区）。
 *
 * 2026-10-17：底部 tab 只有 4 个入口，私信/通知的未读数**在手机上完全看不到**
 * （桌面顶栏那套徽标只存在于 AppShell，/m 不用它），用户因此不知道有消息。
 * 这里把「我的」tab 上加一个数字红点：首页 → 我的 → 私信/通知，形成一条可见的引导路径。
 */
export default function MobileTabBar() {
  const counts = useUnreadCounts();
  const total = counts.signedIn ? counts.dm + counts.notif : 0;

  return (
    <nav className="m-tabbar">
      {TABS.map((t) => {
        const badge = t.to === "/m/me" ? total : 0;
        return (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.to === "/m"}
            aria-label={badge > 0 ? `${t.label}，${badge} 条未读` : t.label}
            className={({ isActive }) => "m-tab" + (isActive ? " active" : "")}
          >
            <span className="m-tab-icon">
              {t.icon}
              {badge > 0 && (
                <span className="m-tab-badge tnum">{formatUnreadCount(badge)}</span>
              )}
            </span>
            <span>{t.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
