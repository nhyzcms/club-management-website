import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSitePolicy } from "../api/sitePolicy";
import AppShell from "../components/AppShell";
import MemberClaimForm from "../components/member/MemberClaimForm";
import PasswordInput from "../components/PasswordInput";
import { useLoginModal } from "../components/LoginModalProvider";
import { useTurnstile } from "../turnstile";
import { IDENTITY_OPTIONS } from "../types/profile";
import type { MemberIdentityStatus } from "../types/member";

/**
 * 注册页（ADR-0006 注册↔认证分离，2026-09 修订）：建登录身份（用户名 + 双密码 + Turnstile）
 * + 真实姓名 / 身份（必填，写入 Profile）；邮箱 / 身份证明仍在登录后的「账号认证」面板。
 *
 * 2026-10（ADR-0025）：注册成功即登录（服务端建会话），并进入「以下身份是否是你」的
 * 社员身份认领阶段（可跳过，之后在个人中心「社员身份」补办）。
 *
 * 后端为权威校验源；前端只做轻量预检（必填、密码一致、长度），其余错误由后端返回展示。
 */
export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [realName, setRealName] = useState("");
  const [identity, setIdentity] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  // 注册后的认领阶段（Part A / ADR-0025）
  const [memberStatus, setMemberStatus] = useState<MemberIdentityStatus | null>(null);
  const [memberLoading, setMemberLoading] = useState(false);
  const [memberErr, setMemberErr] = useState("");
  const [claimed, setClaimed] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const navigate = useNavigate();
  const { openLogin, notifyAuthChange } = useLoginModal();
  const policy = useSitePolicy();
  const { containerRef, token: turnstileToken, reset: resetTurnstile, enabled: turnstileOn, policyReady } =
    useTurnstile();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!policyReady) return;

    if (!username.trim()) {
      setError("请填写用户名。");
      return;
    }
    if (!realName.trim()) {
      setError("请填写真实姓名。");
      return;
    }
    if (!identity) {
      setError("请选择身份。");
      return;
    }
    if (password !== password2) {
      setError("两次输入的密码不一致。");
      return;
    }
    if (password.length < 8) {
      setError("密码至少 8 位。");
      return;
    }
    if (turnstileOn && !turnstileToken) {
      setError("请先完成人机校验。");
      return;
    }

    setLoading(true);
    const fd = new FormData();
    fd.append("username", username.trim());
    fd.append("real_name", realName.trim());
    fd.append("identity", identity);
    fd.append("password", password);
    fd.append("password2", password2);
    if (turnstileToken) fd.append("turnstile_token", turnstileToken);

    try {
      await api.register(fd);
      setDone(true);
      notifyAuthChange(); // 注册即登录：通知 AppShell / 首页刷新为已登录态
      // 注册即登录（ADR-0025）：直接核对社员名册，进入认领阶段。
      setMemberLoading(true);
      api.memberIdentity()
        .then((d: any) => setMemberStatus(d as MemberIdentityStatus))
        .catch((e: any) => setMemberErr(e.message || ""))
        .finally(() => setMemberLoading(false));
    } catch (err: any) {
      setError(err?.message || "注册失败，请稍后重试。");
      resetTurnstile();
    } finally {
      setLoading(false);
    }
  };

  const goLogin = () => {
    navigate("/");
    openLogin();
  };

  /** 注册成功后的三态：核对中 / 认领阶段 / 完成说明。 */
  const renderMemberStage = () => {
    if (memberLoading) {
      return (
        <>
          <h2 style={{ marginBottom: "var(--s-4)" }}>注册成功</h2>
          <p className="muted">正在核对社员名册…</p>
        </>
      );
    }
    if (memberStatus?.enabled && memberStatus.candidates.length > 0 && !claimed && !skipped) {
      return (
        <>
          <h2 style={{ marginBottom: "var(--s-4)" }}>以下身份是否是你？</h2>
          <p className="muted" style={{ marginBottom: "var(--s-4)" }}>
            我们在社员名册中找到了与「{realName.trim()}」一致的身份。绑定后即拥有社员识别码；
            也可以先跳过，之后在个人中心「社员身份」里补办。
          </p>
          <MemberClaimForm candidates={memberStatus.candidates} onDone={() => setClaimed(true)} />
          <button
            className="btn btn-block"
            type="button"
            style={{ marginTop: "var(--s-3)" }}
            onClick={() => setSkipped(true)}
          >
            暂时跳过
          </button>
        </>
      );
    }
    return (
      <>
        <h2 style={{ marginBottom: "var(--s-4)" }}>{claimed ? "认领成功" : "注册成功"}</h2>
        <p className="muted" style={{ marginBottom: "var(--s-5)" }}>
          你已自动登录。
          {claimed
            ? "社员身份已绑定，识别码见个人中心「社员身份」。"
            : skipped
              ? "已跳过身份认领，之后可在个人中心「社员身份」中完成。"
              : memberErr
                ? "名册核对暂时失败，可稍后在个人中心「社员身份」里重试。"
                : "如果社员名单已导入，可稍后在个人中心「社员身份」里试试认领。"}
          在个人中心「账号认证」完成认证（绑定邮箱或提交身份证明），
          即可解锁发帖、发消息、建申报等全部功能。
        </p>
        <button className="btn btn-primary btn-block" type="button" onClick={() => navigate("/")}>
          进入首页
        </button>
      </>
    );
  };

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 460 }}>
          <div style={{ paddingTop: "var(--s-16)", paddingBottom: "var(--s-16)" }}>
            <div className="card card-pad">
              {done ? (
                renderMemberStage()
              ) : !policy.registration_enabled ? (
                <>
                  <h2 style={{ marginBottom: "var(--s-4)" }}>注册已关闭</h2>
                  <p className="muted" style={{ marginBottom: "var(--s-5)" }}>
                    当前未开放自助注册。已有账号可登录。
                  </p>
                  <button className="btn btn-primary btn-block" type="button" onClick={goLogin}>
                    去登录
                  </button>
                </>
              ) : (
                <>
                  <h2 style={{ marginBottom: "var(--s-5)" }}>注册账号</h2>
                  <form
                    onSubmit={handleSubmit}
                    style={{ display: "flex", flexDirection: "column", gap: "var(--s-4)" }}
                  >
                    {error && (
                      <div className="alert alert-danger" role="alert">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
                        <span>{error}</span>
                      </div>
                    )}
                    <div className="field">
                      <label className="label" htmlFor="reg-username">用户名</label>
                      <input
                        className="input"
                        id="reg-username"
                        name="username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        placeholder="登录用用户名"
                        autoComplete="username"
                        spellCheck={false}
                        required
                      />
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="reg-password">密码</label>
                      <PasswordInput
                        id="reg-password"
                        name="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="至少 8 位"
                        autoComplete="new-password"
                      />
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="reg-password2">确认密码</label>
                      <PasswordInput
                        id="reg-password2"
                        name="confirm-password"
                        value={password2}
                        onChange={(e) => setPassword2(e.target.value)}
                        placeholder="再输一次"
                        autoComplete="new-password"
                      />
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="reg-realname">真实姓名</label>
                      <input
                        className="input"
                        id="reg-realname"
                        name="name"
                        value={realName}
                        onChange={(e) => setRealName(e.target.value)}
                        placeholder="用于身份核验，不公开展示"
                        autoComplete="name"
                        maxLength={100}
                        required
                      />
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="reg-identity">身份</label>
                      <select
                        className="input"
                        id="reg-identity"
                        name="identity"
                        value={identity}
                        onChange={(e) => setIdentity(e.target.value)}
                        required
                      >
                        <option value="" disabled>请选择身份</option>
                        {IDENTITY_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    </div>
                    <div ref={containerRef} />
                    <button
                      className="btn btn-primary btn-block"
                      type="submit"
                      disabled={loading || !policyReady}
                    >
                      {loading ? "提交中…" : !policyReady ? "加载中…" : "注册"}
                    </button>
                  </form>
                  <div className="hint center" style={{ marginTop: "var(--s-4)" }}>
                    已有账号？{" "}
                    <a href="#" onClick={(e) => { e.preventDefault(); goLogin(); }}>
                      去登录
                    </a>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
