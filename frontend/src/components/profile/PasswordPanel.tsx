import { useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
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
      await api.changePassword(oldPassword, newPassword);
      setOldPassword(""); setNewPassword(""); setConfirm("");
      setSuccess("密码已修改");
      setTimeout(() => setSuccess(""), 3000);
    } catch (err: any) {
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
