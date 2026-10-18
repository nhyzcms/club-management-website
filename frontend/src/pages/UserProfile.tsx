
import { useEffect, useState } from "react";
import { useParams, useSearchParams, useNavigate, Link } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api } from "../api/client";
import { useLoginModal } from "../components/LoginModalProvider";
import ProfileHero from "../components/profile/ProfileHero";
import ProfileSideNav from "../components/profile/ProfileSideNav";
import ProfileTabs from "../components/profile/ProfileTabs";
import ProfileEditPanel from "../components/profile/ProfileEditPanel";
import PasswordPanel from "../components/profile/PasswordPanel";
import SessionsPanel from "../components/profile/SessionsPanel";
import ContentListPanel from "../components/profile/ContentListPanel";
import PermissionsPanel from "../components/profile/PermissionsPanel";
import VerificationPanel from "../components/profile/VerificationPanel";
import MemberIdentityPanel from "../components/profile/MemberIdentityPanel";
import SecurityPanel from "../components/profile/SecurityPanel";
import MuteUserPanel from "../components/profile/MuteUserPanel";
import NotificationPreferencesPanel from "../components/profile/NotificationPreferencesPanel";
import AccountDeletionPanel from "../components/profile/AccountDeletionPanel";
import ReportButton from "../components/ReportButton";
import { messagingApi } from "../api/messaging";
import type { UserProfileData } from "../types/profile";
import "../styles/profile.css";

const SELF_TABS = [
  { key: "profile", label: "资料编辑" },
  { key: "verification", label: "账号认证" },
  { key: "member", label: "社员身份" },
  { key: "security", label: "安全验证" },
  { key: "notify", label: "通知" },
  { key: "password", label: "改密码" },
  { key: "sessions", label: "登录记录" },
  { key: "news", label: "我的新闻", divider: true },
  { key: "activities", label: "我的活动" },
  { key: "tutorials", label: "我的教程" },
  { key: "feedback", label: "我的反馈" },
  { key: "tasks", label: "我的任务" },
  { key: "permissions", label: "我的权限", divider: true },
  { key: "delete", label: "注销账号" },
];

export default function UserProfile() {
  const { id } = useParams<{ id: string }>();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const { openLogin, notifyAuthChange } = useLoginModal();
  const [profile, setProfile] = useState<UserProfileData | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [canMute, setCanMute] = useState(false);
  const [canDm, setCanDm] = useState(false);
  const [dmBusy, setDmBusy] = useState(false);
  const [dmError, setDmError] = useState("");

  const uid = Number(id);

  useEffect(() => {
    setProfile(null);
    setNotFound(false);
    setLoadErr("");
    api.getUserProfile(uid)
      .then((d: any) => setProfile(d))
      .catch((e: any) => {
        if (e.status === 401) openLogin();
        else if (e.status === 404) setNotFound(true);
        else setLoadErr(e.message || "加载失败");
      });
    api.me()
      .then((d: any) => {
        setCanMute(!!d.user?.permissions?.can_mute_user);
        setCanDm(!!d.profile?.is_verified);
      })
      .catch(() => { setCanMute(false); setCanDm(false); });
  }, [uid, openLogin]);

  if (notFound || loadErr) {
    return (
      <AppShell>
        <div className="container" style={{ paddingTop: "var(--s-12)" }}>
          <p className="muted">{notFound ? "用户不存在。" : loadErr}</p>
        </div>
      </AppShell>
    );
  }
  if (!profile) {
    return (
      <AppShell>
        <div className="container" style={{ paddingTop: "var(--s-12)" }}>
          <p className="muted">加载中…</p>
        </div>
      </AppShell>
    );
  }

  const isOwner = profile.viewer.is_owner;
  const isAdmin = profile.viewer.is_admin;

  if (profile.deleted) {
    return (
      <AppShell>
        <div className="container" style={{ paddingTop: "var(--s-12)", paddingBottom: "var(--s-16)" }}>
          <div className="card card-pad" style={{ maxWidth: 560, margin: "0 auto", textAlign: "center" }}>
            <h1 style={{ fontSize: 20, marginBottom: "var(--s-3)" }}>该用户已注销</h1>
            <p className="muted" style={{ marginBottom: "var(--s-4)" }}>
              该账号已由本人主动注销，资料与联系方式不再公开展示；历史私信与评论仍保留。
            </p>
            <Link className="btn btn-secondary" to="/">返回首页</Link>
          </div>
        </div>
      </AppShell>
    );
  }

  const tabs = isOwner
    ? SELF_TABS
    : [
        { key: "news", label: "ta 的新闻" },
        { key: "activities", label: "ta 的活动" },
        { key: "tutorials", label: "ta 的教程" },
        ...(isAdmin ? [{ key: "permissions", label: "权限" }] : []),
      ];

  const defaultTab = isOwner ? "profile" : "news";
  const tabKeys = tabs.map((t) => t.key);
  const rawTab = search.get("tab");
  const active = rawTab && tabKeys.includes(rawTab) ? rawTab : defaultTab;

  const setTab = (k: string) => {
    const next = new URLSearchParams(search);
    next.set("tab", k);
    setSearch(next, { replace: true });
  };

  const startDm = async () => {
    setDmBusy(true);
    setDmError("");
    try {
      const conv = await messagingApi.startPrivate(uid);
      navigate(`/messages/${conv.id}`);
    } catch (e: any) {
      setDmError(e?.message || "无法发起私信");
    } finally {
      setDmBusy(false);
    }
  };

  const onProfileSaved = () => {
    api.getUserProfile(uid).then((d: any) => setProfile(d)).catch((e: any) => console.warn("profile refetch failed", e));
    notifyAuthChange();
  };

  return (
    <AppShell>
      <ProfileHero profile={profile} onEdit={isOwner ? () => setTab("profile") : undefined} />

      <div className="container profile-body">
        {isOwner ? (
          <div className="profile-layout">
            <ProfileSideNav tabs={tabs} active={active} onPick={setTab} />
            <div className="profile-panel">
              {active === "profile" && <ProfileEditPanel onSaved={onProfileSaved} />}
              {active === "verification" && <VerificationPanel />}
              {active === "member" && <MemberIdentityPanel />}
              {active === "security" && <SecurityPanel />}
              {active === "notify" && <NotificationPreferencesPanel />}
              {active === "password" && <PasswordPanel />}
              {active === "sessions" && <SessionsPanel />}
              {active === "news" && <ContentListPanel userId={uid} type="news" selfView />}
              {active === "activities" && <ContentListPanel userId={uid} type="activities" selfView />}
              {active === "tutorials" && <ContentListPanel userId={uid} type="tutorials" selfView />}
              {active === "feedback" && <ContentListPanel userId={uid} type="feedback" selfView />}
              {active === "tasks" && <ContentListPanel userId={uid} type="tasks" selfView />}
              {active === "permissions" && <PermissionsPanel profile={profile} />}
              {active === "delete" && <AccountDeletionPanel />}
            </div>
          </div>
        ) : (
          <div className="profile-other">
            <ProfileTabs tabs={tabs} active={active} onPick={setTab} />
            <div className="profile-panel">
              {canDm && (
                <div style={{ marginBottom: "var(--s-4)", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
                  {dmError && <div className="alert alert-danger" style={{ marginBottom: 8 }}><span>{dmError}</span></div>}
                  <button className="btn btn-secondary btn-sm" type="button" onClick={startDm} disabled={dmBusy}>
                    {dmBusy ? "打开中…" : "发私信"}
                  </button>
                  <ReportButton targetType="user" targetId={uid} isOwn={false} compact />
                </div>
              )}
              {canMute && <MuteUserPanel userId={uid} />}
              {active === "news" && <ContentListPanel userId={uid} type="news" selfView={false} />}
              {active === "activities" && <ContentListPanel userId={uid} type="activities" selfView={false} />}
              {active === "tutorials" && <ContentListPanel userId={uid} type="tutorials" selfView={false} />}
              {active === "permissions" && <PermissionsPanel profile={profile} />}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
