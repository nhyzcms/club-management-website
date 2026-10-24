import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import PasswordInput from "../components/PasswordInput";
import { useLoginModal } from "../components/LoginModalProvider";

/**
 * 强制改密页（/#/change-password-required）。
 *
 * 触发：管理员批准「手动重置密码」后，账号密码被重置为 123456 且置
 * ``Profile.must_change_password``；登录接口返回 must_change_password=true，
 * 其他接口被后端中间件拦下（403 password_change_required）时本页也是统一落脚点。
 */
export default function ForcePasswordChangePage() {
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { notifyAuthChange } = useLoginModal();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("新密码至少 8 位。");
      return;
    }
    if (password !== password2) {
      setError("两次输入的密码不一致。");
      return;
    }
    if (password === "123456") {
      setError("新密码不能与默认密码相同。");
      return;
    }
    setLoading(true);
    try {
      await api.forceChangePassword(password, password2);
      notifyAuthChange();
      navigate("/");
    } catch (err: any) {
      if (err?.apiError?.kind === "http" && err?.apiError?.status === 400) {
        setError(err.message || "修改失败，请重试。");
      } else {
        setError(err?.message || "修改失败，请稍后重试。");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 460 }}>
          <div style={{ paddingTop: "var(--s-16)", paddingBottom: "var(--s-16)" }}>
            <div className="card card-pad">
              <h2 style={{ marginBottom: "var(--s-3)" }}>请修改密码</h2>
              <p className="muted" style={{ marginBottom: "var(--s-5)" }}>
                管理员已为你重置密码（默认 123456）。为了账号安全，首次登录必须设置新密码后才能继续使用。
              </p>
              <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--s-4)" }}>
                {error && (
                  <div className="alert alert-danger" role="alert">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
                    <span>{error}</span>
                  </div>
                )}
                <div className="field">
                  <label className="label" htmlFor="force-pw">新密码</label>
                  <PasswordInput id="force-pw" name="new_password" placeholder="至少 8 位" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required />
                </div>
                <div className="field">
                  <label className="label" htmlFor="force-pw2">确认新密码</label>
                  <PasswordInput id="force-pw2" name="new_password2" placeholder="再次输入新密码" value={password2} onChange={(e) => setPassword2(e.target.value)} autoComplete="new-password" required />
                </div>
                <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
                  {loading ? "保存中…" : "保存并继续"}
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
