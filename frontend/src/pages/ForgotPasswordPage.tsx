import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import { useLoginModal } from "../components/LoginModalProvider";
import { useTurnstile } from "../turnstile";

type Mode = "email" | "manual";

/**
 * 忘记密码（2026-10 双通道）：
 * - 邮箱找回：原有自助链路（已认证邮箱收重置链接）；
 * - 联系管理员：给没有可用邮箱的社员——提交账号 + 身份证明，管理员在审核台核对后
 *   把密码重置为默认值，首次登录强制改密。
 */
export default function ForgotPasswordPage() {
  const [mode, setMode] = useState<Mode>("email");
  const [email, setEmail] = useState("");
  const [account, setAccount] = useState("");
  const [contact, setContact] = useState("");
  const [note, setNote] = useState("");
  const [proof, setProof] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { openLogin } = useLoginModal();
  const { containerRef, token, reset, enabled, policyReady } = useTurnstile();

  const switchMode = (next: Mode) => {
    if (next === mode) return;
    setMode(next);
    setError("");
    setSuccess("");
    reset();
  };

  const handleEmailSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (!policyReady) return;
    if (enabled && !token) {
      setError("请先完成人机校验。");
      return;
    }
    setLoading(true);
    try {
      await api.passwordReset(email, token);
      setSuccess("如果该邮箱已注册，重置链接已发送，请查看控制台输出。");
    } catch (err: any) {
      setError(err.message);
      reset();
    } finally {
      setLoading(false);
    }
  };

  const handleManualSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (!policyReady) return;
    if (!account.trim()) {
      setError("请填写用户名或邮箱。");
      return;
    }
    if (!proof) {
      setError("请上传身份证明（学生证/校牌）。");
      return;
    }
    if (enabled && !token) {
      setError("请先完成人机校验。");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("account", account.trim());
      fd.append("contact", contact.trim());
      fd.append("note", note.trim());
      fd.append("proof", proof);
      if (token) fd.append("turnstile_token", token);
      const result: any = await api.passwordResetRequest(fd);
      setSuccess(result?.message || "申请已提交，请等待管理员审核。");
      setProof(null);
    } catch (err: any) {
      setError(err.message);
      reset();
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 480 }}>
          <div style={{ paddingTop: "var(--s-16)", paddingBottom: "var(--s-16)" }}>
            <div className="card card-pad">
              <h2 style={{ marginBottom: "var(--s-5)" }}>忘记密码</h2>

              <div className="seg seg-sm" role="tablist" aria-label="找回方式" style={{ marginBottom: "var(--s-5)" }}>
                <button
                  className="seg-btn"
                  type="button"
                  role="tab"
                  aria-selected={mode === "email"}
                  onClick={() => switchMode("email")}
                >
                  邮箱找回
                </button>
                <button
                  className="seg-btn"
                  type="button"
                  role="tab"
                  aria-selected={mode === "manual"}
                  onClick={() => switchMode("manual")}
                >
                  联系管理员
                </button>
              </div>

              {error && (
                <div className="alert alert-danger" role="alert" style={{ marginBottom: "var(--s-4)" }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
                  <span>{error}</span>
                </div>
              )}
              {success && (
                <div className="alert alert-success" role="status" style={{ marginBottom: "var(--s-4)" }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
                  <span>{success}</span>
                </div>
              )}

              {mode === "email" ? (
                <form onSubmit={handleEmailSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--s-4)" }}>
                  <div className="field">
                    <label className="label" htmlFor="fp-email">邮箱</label>
                    <input className="input" id="fp-email" name="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="请输入注册邮箱" autoComplete="email" spellCheck={false} required />
                  </div>
                  <div ref={containerRef} />
                  <button className="btn btn-primary btn-block" type="submit" disabled={loading || !policyReady}>
                    {loading ? "发送中…" : !policyReady ? "加载中…" : "发送重置链接"}
                  </button>
                </form>
              ) : (
                <form onSubmit={handleManualSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--s-4)" }}>
                  <p className="hint" style={{ margin: 0 }}>
                    邮箱无法使用或未绑定邮箱时，可向管理员申请手动重置。请上传<b>学生证/校牌</b>照片作为
                    身份证明（能看清姓名、班级即可，其他信息可打码）；管理员核对后会重置密码，首次登录需立即修改。
                    <b>请勿提交身份证照片</b>——本站不需要身份证等敏感证件，管理员也不会索要。
                  </p>
                  <div className="field">
                    <label className="label" htmlFor="fp-account">用户名 / 邮箱</label>
                    <input className="input" id="fp-account" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="用于定位你的账号" autoComplete="username" spellCheck={false} required />
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="fp-contact">联系方式（选填）</label>
                    <input className="input" id="fp-contact" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="手机 / QQ / 微信，便于管理员联系" />
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="fp-note">申请说明（选填）</label>
                    <textarea className="textarea" id="fp-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="例如：换了手机号，原邮箱已无法登录" />
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="fp-proof">身份证明（学生证/校牌，必填，≤5MB，JPG / PNG / WebP）</label>
                    <input className="input" id="fp-proof" type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setProof(e.target.files?.[0] ?? null)} required />
                    {proof && <p className="hint" style={{ margin: 0 }}>已选择：{proof.name}</p>}
                    <p className="hint" style={{ margin: 0 }}>请勿上传身份证照片。</p>
                  </div>
                  <div ref={containerRef} />
                  <button className="btn btn-primary btn-block" type="submit" disabled={loading || !policyReady}>
                    {loading ? "提交中…" : !policyReady ? "加载中…" : "提交申请"}
                  </button>
                </form>
              )}

              <div className="hint center" style={{ marginTop: "var(--s-4)" }}>
                <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); openLogin(); }}>返回登录</a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
