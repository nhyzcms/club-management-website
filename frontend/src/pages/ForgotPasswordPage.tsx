import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import { useLoginModal } from "../components/LoginModalProvider";
import { useTurnstile } from "../turnstile";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { openLogin } = useLoginModal();
  const { containerRef, token, reset, enabled, policyReady } = useTurnstile();

  const handleSubmit = async (e: FormEvent) => {
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

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 440 }}>
          <div style={{ paddingTop: "var(--s-16)", paddingBottom: "var(--s-16)" }}>
            <div className="card card-pad">
              <h2 style={{ marginBottom: "var(--s-5)" }}>忘记密码</h2>
              <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--s-4)" }}>
                {error && (
                  <div className="alert alert-danger" role="alert">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
                    <span>{error}</span>
                  </div>
                )}
                {success && (
                  <div className="alert alert-success" role="status">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
                    <span>{success}</span>
                  </div>
                )}
                <div className="field">
                  <label className="label" htmlFor="fp-email">邮箱</label>
                  <input className="input" id="fp-email" name="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="请输入注册邮箱" autoComplete="email" spellCheck={false} required />
                </div>
                <div ref={containerRef} />
                <button className="btn btn-primary btn-block" type="submit" disabled={loading || !policyReady}>
                  {loading ? "发送中…" : !policyReady ? "加载中…" : "发送重置链接"}
                </button>
              </form>
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
