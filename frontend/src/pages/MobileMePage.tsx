import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLoginModal } from "../components/LoginModalProvider";
import MobileTabBar from "../components/MobileTabBar";
import { formatUnreadCount, useUnreadCounts } from "../api/unreadBadges";
import { THEME_OPTIONS, useTheme } from "../theme";
import type { RoleVariant } from "../types/profile";
import { canAccessAdmin } from "../utils/roles";
import { isAppShell } from "../utils/device";
import "../styles/mobile.css";
import "../styles/mobile-work.css";

/** /auth/me/（accounts.views._profile_response）真实返回结构：身份在 role、
 * 资料在 profile，user 上仅有 id/username/email/permissions。 */
interface MeResponse {
  user: {
    id: number;
    username: string;
    email: string;
    permissions?: {
      can_review_content?: boolean;
      can_review_identity?: boolean;
      can_view_feedback?: boolean;
      can_handle_reports?: boolean;
      can_review_password_reset?: boolean;
      can_manage_exam?: boolean;
    };
  };
  role: { label: string; variant: RoleVariant };
  profile: { avatar: string | null; nickname: string; is_verified: boolean };
}

interface Entry {
  to: string;
  label: string;
  badge?: "dm" | "notif";
  hint?: string;
}

/**
 * 手机版「我的」。
 *
 * 2026-10-18：新增「工作」分组，把桌面端的工作台功能（审核台、待办、任务、
 * 通知）接到手机版。权限派生与桌面 AppShell 一致：
 * - 审核台：任一审核能力（内容/身份/反馈/举报）即可见；
 * - 待办：需已认证（与 /auth/inbox/ 的门禁一致）；
 * - 任务与通知：登录即可。
 */
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
  const permissions = user?.permissions ?? {};
  const isVerified = !!me?.profile?.is_verified;
  const showReview = !!(
    permissions.can_review_content ||
    permissions.can_review_identity ||
    permissions.can_view_feedback ||
    permissions.can_handle_reports ||
    permissions.can_review_password_reset
  );
  // 「进入后台管理」指向 Django admin（其门禁只认 is_staff），与桌面顶栏菜单同一判定
  const isAdmin = canAccessAdmin(me?.role?.variant);
  // 手机版考试看板只提供编辑面板，入口按真实权限出现（与 /exam 页面内的判定一致）
  const canManageExam = !!permissions.can_manage_exam;

  /**
   * 2026-11-02：精简「我的」——别处能到达的入口不在这里重复列：
   * - 任务 / 待办 / 社员查询：首页九宫格已有；
   * - 全景图：关于我们 →「校园全景图」已有；
   * - 登录设备 / 注销账号：个人资料页内已有。
   */
  const common: Entry[] = [
    { to: "/m/notifications", label: "通知", badge: "notif" },
    { to: "/messages", label: "私信", badge: "dm" },
    { to: "/profile", label: "个人资料", hint: "资料 / 认证 / 登录设备 / 注销账号" },
    { to: "/feedback", label: "意见反馈" },
  ];

  const work: Entry[] = [
    ...(showReview
      ? [{ to: "/m/review", label: "审核台", hint: "身份 / 内容 / 反馈 / 举报 / 密码重置" }]
      : []),
    ...(canManageExam
      ? [{ to: "/exam", label: "考试日程编辑", hint: "批次、科目与考试时间" }]
      : []),
    ...(isAdmin ? [{ to: "/admin/", label: "进入后台管理" }] : []),
  ];

  /** 桌面版页面，手机上暂时没有专门版式（区块 8 的"允许降级但必须有入口"）。
   * 这些页面本身是响应式的，只是顶栏仍是桌面布局；先保证能到达、能操作，
   * 后续按实际使用频率再逐页做 /m 版本。
   */
  const more: Entry[] = [
    { to: "/schedule", label: "课表", hint: "本周课程一览" },
    { to: "/about", label: "关于我们", hint: "社团简介、校园全景与联系方式" },
    // App 专属：只在壳里出现（手机浏览器 / 桌面都看不到这一项，路由侧还有一道门禁）
    ...(isAppShell()
      ? [{ to: "/m/about-app", label: "关于 APP", hint: "版本、开源协议与官网" }]
      : []),
  ];

  const badgeOf = (kind?: "dm" | "notif") => {
    if (!kind || !counts.signedIn) return 0;
    return kind === "dm" ? counts.dm : counts.notif;
  };

  const open = (to: string) => {
    if (to.startsWith("http")) window.location.href = to;
    else if (to === "/admin/") window.location.href = "/admin/";
    else navigate(to);
  };

  const renderGroup = (title: string, entries: Entry[]) => {
    if (entries.length === 0) return null;
    return (
      <>
        <div className="m-list-group-title">{title}</div>
        <div className="m-list">
          {entries.map((e) => {
            const badge = badgeOf(e.badge);
            return (
              <div
                key={e.to}
                role="link"
                tabIndex={0}
                className="m-list-item"
                onClick={() => open(e.to)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter") open(e.to);
                }}
              >
                <span className="m-list-label">
                  {e.label}
                  {e.hint && <span className="m-list-hint">{e.hint}</span>}
                </span>
                {badge > 0 && <span className="m-count-badge tnum">{formatUnreadCount(badge)}</span>}
              </div>
            );
          })}
        </div>
      </>
    );
  };

  return (
    <div className="m-app">
      <header className="m-topbar">
        <div className="m-brand">我的</div>
      </header>

      <section className="m-me-card">
        {user ? (
          <>
            <img
              className="m-me-avatar"
              src={me?.profile?.avatar || "/static/favicon.ico"}
              alt=""
              width={56}
              height={56}
            />
            <div>
              <div className="m-me-name">{me?.profile?.nickname || user.username}</div>
              <div className="m-me-sub">
                @{user.username} · {me?.role?.label ?? ""}
                {isVerified ? "" : " · 未认证"}
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

      {/* 外观：手机上没有桌面顶栏的主题切换入口，这里保留三档分段控件。 */}
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

      {user && renderGroup("工作", work)}
      {renderGroup("常用", common)}
      {renderGroup("更多", more)}

      {user && (
        <div className="m-list">
          <button
            className="m-list-item m-list-danger"
            onClick={() => {
              api.logout().then(() => window.location.reload());
            }}
          >
            退出登录
          </button>
        </div>
      )}

      <MobileTabBar />
    </div>
  );
}
