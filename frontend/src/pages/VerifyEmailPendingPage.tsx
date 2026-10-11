import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import { useLoginModal } from "../components/LoginModalProvider";
import { useTurnstile } from "../turnstile";

/**
 * 邮箱验证待办 / 重发页（#29）：输入邮箱重发验证邮件。
 * 登录被「未验证」拒绝时跳来此；email 可由 query 预填。后端对不存在 / 已验证邮箱同样回成功提示（防探测）。
 */
export default function VerifyEmailPendingPage() {
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState(searchParams.get("email") || "");
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
    if (!email.trim()) {
      setError("请输入邮箱。");
      return;
    }
    if (enabled && !token) {
      setError("请先完成人机校验。");
      return;
    }
    setLoading(true);
    try {
      await api.resendVerification(email.trim(), token);
      setSuccess("如果该邮箱已注册且尚未验证，验证邮件已重发，请查收（含垃圾邮件箱）。");
    } catch (err: any) {
      setError(err?.message || "发送失败，请稍后重试。");
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
              <h2 style={{ marginBottom: "var(--s-5)" }}>重发验证邮件</h2>
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
                  <label className="label" htmlFor="ve-email">注册邮箱</label>
                  <input
                    className="input"
                    id="ve-email"
                    name="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="请输入注册时的邮箱"
                    autoComplete="email"
                    spellCheck={false}
                    required
                  />
                </div>
                <div ref={containerRef} />
                <button className="btn btn-primary btn-block" type="submit" disabled={loading || !policyReady}>
                  {loading ? "发送中…" : !policyReady ? "加载中…" : "发送验证邮件"}
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
