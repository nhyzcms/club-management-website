import { useState, FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import PasswordInput from "../components/PasswordInput";
import { useLoginModal } from "../components/LoginModalProvider";

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const uid = searchParams.get("uid") || "";
  const token = searchParams.get("token") || "";
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { openLogin } = useLoginModal();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.passwordResetConfirm(uid, token, newPassword);
      navigate("/");
      openLogin();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const invalid = !uid || !token;

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 440 }}>
          <div style={{ paddingTop: "var(--s-16)", paddingBottom: "var(--s-16)" }}>
            <div className="card card-pad">
              {invalid ? (
                <>
                  <h2 style={{ marginBottom: "var(--s-4)" }}>链接无效</h2>
                  <p className="muted" style={{ marginBottom: "var(--s-5)" }}>该密码重置链接无效或已过期。</p>
                  <div className="hint center">
                    <a href="#" onClick={(e) => { e.preventDefault(); navigate("/"); openLogin(); }}>返回登录</a>
                  </div>
                </>
              ) : (
                <>
                  <h2 style={{ marginBottom: "var(--s-5)" }}>重置密码</h2>
                  <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--s-4)" }}>
                    {error && (
                      <div className="alert alert-danger" role="alert">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
                        <span>{error}</span>
                      </div>
                    )}
                    <div className="field">
                      <label className="label" htmlFor="rp-password">新密码</label>
                      <PasswordInput id="rp-password" name="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="至少 8 个字符" autoComplete="new-password" required />
                    </div>
                    <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
                      {loading ? "重置中…" : "重置密码"}
                    </button>
                  </form>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
