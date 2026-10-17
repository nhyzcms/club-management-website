import { Fragment, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import Avatar from "./Avatar";
import { THEME_OPTIONS, type ThemePreference } from "../theme";

/** 16px 线性图标集（与站内 Caret / 提示条图标同风格：stroke=currentColor）。 */
const ico = (children: ReactNode) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {children}
  </svg>
);

const ICONS = {
  profile: ico(
    <>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </>
  ),
  mail: ico(
    <>
      <path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
      <path d="m22 6-10 7L2 6" />
    </>
  ),
  bell: ico(
    <>
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </>
  ),
  todo: ico(
    <>
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </>
  ),
  tasks: ico(
    <>
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <rect x="8" y="2" width="8" height="4" rx="1" />
    </>
  ),
  activity: ico(
    <>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </>
  ),
  feedback: ico(
    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
  ),
  review: ico(
    <>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="m9 11.5 2.1 2.1L15.5 9" />
    </>
  ),
  admin: ico(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </>
  ),
  logout: ico(
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </>
  ),
};

interface UserMenuUser {
  id: number;
  username: string;
}

interface UserMenuProfile {
  nickname?: string;
  avatar?: string | null;
}

export interface UserMenuProps {
  user: UserMenuUser;
  profile: UserMenuProfile;
  /** 已通过账号验证（决定「私信 / 待办」可见性） */
  verified: boolean;
  /** 站点私信开关（SiteSettings.dms_enabled） */
  dmsEnabled: boolean;
  /** 审核台权限（决定「审核队列」可见性） */
  canReview: boolean;
  themePref: ThemePreference;
  onThemeSelect: (pref: ThemePreference) => void;
  onNavigate: (path: string) => void;
  onLogout: () => void;
}

interface MenuEntry {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  dividerBefore?: boolean;
}

/**
 * 顶栏头像菜单（GitHub 式）：
 * - 触发器为纯头像按钮；菜单打开即聚焦第一项，↑↓ 循环、Esc 关闭并归还焦点、点外部关闭；
 * - roving tabindex + role=menu/menuitem，外观分组为 menuitemradio（与主题系统联动）。
 */
export default function UserMenu({
  user,
  profile,
  verified,
  dmsEnabled,
  canReview,
  themePref,
  onThemeSelect,
  onNavigate,
  onLogout,
}: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const name = profile.nickname || user.username;
  const avatarUser = {
    id: user.id,
    username: user.username,
    nickname: profile.nickname,
    avatar: profile.avatar ?? null,
  };

  const navItems = () =>
    Array.from(menuRef.current?.querySelectorAll<HTMLElement>("[data-um-item]:not([hidden])") ?? []);

  const close = (refocusTrigger = false) => {
    setOpen(false);
    if (refocusTrigger) requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const moveFocus = (delta: 1 | -1) => {
    const items = navItems();
    if (items.length === 0) return;
    const cur = items.indexOf(document.activeElement as HTMLElement);
    const next =
      cur === -1 ? (delta === 1 ? 0 : items.length - 1) : (cur + delta + items.length) % items.length;
    items[next]?.focus();
  };

  // 打开后聚焦第一项（对标 GitHub：打开即进入菜单）
  useEffect(() => {
    if (!open) return;
    const raf = requestAnimationFrame(() => navItems()[0]?.focus());
    return () => cancelAnimationFrame(raf);
  }, [open]);

  // 点击组件外部关闭
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div
      className="usermenu-wrap"
      ref={wrapRef}
      onBlur={(e) => {
        // 焦点离开整个组件（Tab 走开等）时关闭；菜单内部移动不受影响
        const next = e.relatedTarget as Node | null;
        if (next && wrapRef.current?.contains(next)) return;
        requestAnimationFrame(() => {
          if (!wrapRef.current?.contains(document.activeElement)) setOpen(false);
        });
      }}
    >
      <button
        ref={triggerRef}
        id="user-menu-trigger"
        className="usermenu-trigger"
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="user-menu-list"
        aria-label="打开用户菜单"
        onClick={() => (open ? close(false) : setOpen(true))}
        onKeyDown={(e) => {
          if (e.key !== "ArrowDown") return;
          e.preventDefault();
          if (!open) setOpen(true);
          else navItems()[0]?.focus();
        }}
      >
        <Avatar user={avatarUser} size="md" />
      </button>

      {open && (
        <div
          ref={menuRef}
          id="user-menu-list"
          className="user-menu is-open"
          role="menu"
          aria-label="用户菜单"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close(true);
              return;
            }
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              moveFocus(e.key === "ArrowDown" ? 1 : -1);
            }
          }}
          onFocus={(e) => {
            // roving tabindex：任一时刻只有当前项可被 Tab 命中（其余 -1）
            const target = (e.target as HTMLElement).closest<HTMLElement>("[data-um-item]");
            if (!target) return;
            for (const el of navItems()) el.tabIndex = el === target ? 0 : -1;
          }}
        >
          <div className="um-head" role="presentation">
            <Avatar user={avatarUser} size="md" />
            <div className="um-ident">
              <div className="um-name">{name}</div>
              <div className="um-sub">@{user.username}</div>
            </div>
          </div>

          {entriesOf({ verified, dmsEnabled, canReview, onNavigate }).map((en, i) => (
            <Fragment key={en.key}>
              {en.dividerBefore && <div className="um-sep" role="separator" />}
              <button
                type="button"
                role="menuitem"
                className="user-menu-item"
                data-um-item={en.key}
                tabIndex={i === 0 ? 0 : -1}
                onClick={() => {
                  en.onSelect();
                  close(false);
                }}
              >
                {en.icon}
                {en.label}
              </button>
            </Fragment>
          ))}

          <div className="um-sep" role="separator" />
          <div className="um-theme" role="group" aria-label="外观">
            <span className="um-theme-label" aria-hidden="true">外观</span>
            {THEME_OPTIONS.map((o) => (
              <button
                key={o.value}
                type="button"
                role="menuitemradio"
                aria-checked={themePref === o.value}
                data-um-item={`theme-${o.value}`}
                tabIndex={-1}
                className={"user-menu-item theme-opt" + (themePref === o.value ? " is-current" : "")}
                onClick={() => onThemeSelect(o.value)}
              >
                <span className="theme-dot" aria-hidden="true" />
                {o.label}
              </button>
            ))}
          </div>

          <div className="um-sep" role="separator" />
          <button
            type="button"
            role="menuitem"
            className="user-menu-item danger"
            data-um-item="logout"
            tabIndex={-1}
            onClick={() => {
              close(false);
              onLogout();
            }}
          >
            {ICONS.logout}
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}

/** 主条目（内容组 + 站务组）；外观 / 退出登录为固定区段，单独渲染。 */
function entriesOf({
  verified,
  dmsEnabled,
  canReview,
  onNavigate,
}: {
  verified: boolean;
  dmsEnabled: boolean;
  canReview: boolean;
  onNavigate: (path: string) => void;
}): MenuEntry[] {
  const entries: MenuEntry[] = [
    { key: "profile", label: "个人中心", icon: ICONS.profile, onSelect: () => onNavigate("/profile") },
  ];
  if (verified && dmsEnabled) {
    entries.push({ key: "messages", label: "私信", icon: ICONS.mail, onSelect: () => onNavigate("/messages") });
  }
  entries.push({ key: "notifications", label: "通知", icon: ICONS.bell, onSelect: () => onNavigate("/notifications") });
  if (verified) {
    entries.push({ key: "inbox", label: "待办", icon: ICONS.todo, onSelect: () => onNavigate("/inbox") });
  }
  entries.push(
    { key: "tasks", label: "任务管理", icon: ICONS.tasks, dividerBefore: true, onSelect: () => onNavigate("/tasks") },
    { key: "activity", label: "活动", icon: ICONS.activity, onSelect: () => onNavigate("/activity") },
    { key: "feedback", label: "意见反馈", icon: ICONS.feedback, onSelect: () => onNavigate("/feedback") },
  );
  if (canReview) {
    entries.push({ key: "reviews", label: "审核队列", icon: ICONS.review, onSelect: () => onNavigate("/reviews") });
  }
  entries.push({ key: "admin", label: "后台管理", icon: ICONS.admin, onSelect: () => onNavigate("/admin/") });
  return entries;
}
