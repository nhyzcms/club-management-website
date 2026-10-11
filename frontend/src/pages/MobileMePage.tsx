import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLoginModal } from "../components/LoginModalProvider";
import MobileTabBar from "../components/MobileTabBar";
import type { RoleVariant } from "../types/profile";
import "../styles/mobile.css";

/** /auth/me/（accounts.views._profile_response）真实返回结构：
 * 身份在 role、资料在 profile，user 上仅有 id/username/email/permissions。 */
interface MeResponse {
  user: { id: number; username: string; email: string };
  role: { label: string; variant: RoleVariant };
  profile: { avatar: string | null; nickname: string; is_verified: boolean };
}

const ENTRIES = [
  { to: "/profile", label: "个人资料" },
  { to: "/tasks", label: "我的任务" },
  { to: "/messages", label: "私信" },
  { to: "/feedback", label: "意见反馈" },
];

export default function MobileMePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const { openLogin } = useLoginModal();
  const navigate = useNavigate();
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

      <div className="m-list">
        {ENTRIES.map((e) => (
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
            {e.label}
          </div>
        ))}
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
            进入后台管理
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
