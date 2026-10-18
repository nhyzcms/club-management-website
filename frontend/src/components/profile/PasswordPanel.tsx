import { useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { redirectToStepUp, stepupHeaders } from "../../api/stepup";
import PasswordInput from "../PasswordInput";
import "../../styles/form.css";

export default function PasswordPanel() {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);
  const oldRef = useRef<HTMLInputElement>(null);
  const newRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (newPassword !== confirm) { setError("两次输入的密码不一致"); confirmRef.current?.focus(); return; }
    if (newPassword.length < 8) { setError("新密码至少 8 个字符"); newRef.current?.focus(); return; }
    setSaving(true);
    try {
      // 敏感操作：带安全验证 grant（ADR-0026）；缺 / 过期时后端 403，跳验证页后回来重试。
      await api.changePassword(oldPassword, newPassword, stepupHeaders("change_password"));
      setOldPassword(""); setNewPassword(""); setConfirm("");
      setSuccess("密码已修改");
      setTimeout(() => setSuccess(""), 3000);
    } catch (err: any) {
      if (err?.status === 403) {
        redirectToStepUp("change_password", "/profile?tab=password");
        return;
      }
      setError(err.message);
      oldRef.current?.focus();
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="card card-pad form-stack" onSubmit={submit}>
      {success && <div className="alert alert-success" role="status"><span>{success}</span></div>}
      {error && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}
      <p className="muted" style={{ marginBottom: "var(--s-3)" }}>
        修改密码前需要完成<strong>安全验证</strong>（邮箱验证码或安全问题）——提交后如需验证会自动跳转，完成即回本页重试。
      </p>
      <div className="field">
        <label className="label" htmlFor="pw-old">原密码</label>
        <PasswordInput id="pw-old" ref={oldRef} name="current-password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} autoComplete="current-password" required />
      </div>
      <div className="form-grid">
        <div className="field">
          <label className="label" htmlFor="pw-new">新密码</label>
          <PasswordInput id="pw-new" ref={newRef} name="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" required minLength={8} />
        </div>
        <div className="field">
          <label className="label" htmlFor="pw-confirm">确认新密码</label>
          <PasswordInput id="pw-confirm" ref={confirmRef} name="confirm-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
        </div>
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "修改中…" : "确认修改"}</button>
      </div>
    </form>
  );
}
