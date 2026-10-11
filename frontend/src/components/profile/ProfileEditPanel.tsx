import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import "../../styles/form.css";

const GENDER_OPTIONS = [
  { value: "", label: "未设置" },
  { value: "M", label: "男" },
  { value: "F", label: "女" },
  { value: "O", label: "其他" },
];

/** 资料编辑面板（仅自己可用）。保存成功后调 onSaved，由父组件刷新 Hero + 顶栏。 */
export default function ProfileEditPanel({ onSaved }: { onSaved: () => void }) {
  const [nickname, setNickname] = useState("");
  const [birthday, setBirthday] = useState("");
  const [gender, setGender] = useState("");
  const [bio, setBio] = useState("");
  const [avatar, setAvatar] = useState<string | null>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.getProfile()
      .then((d: any) => {
        setNickname(d.profile.nickname);
        setBirthday(d.profile.birthday || "");
        setGender(d.profile.gender);
        setBio(d.profile.bio);
        setAvatar(d.profile.avatar);
      })
      .finally(() => setLoading(false));
  }, []);

  const onAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 2 * 1024 * 1024) { setError("头像文件不能超过 2MB"); return; }
    const reader = new FileReader();
    reader.onload = (ev) => setAvatarPreview(ev.target?.result as string);
    reader.readAsDataURL(f);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setSaving(true);
    try {
      const fd = new FormData();
      if (avatarPreview) {
        const f = fileRef.current?.files?.[0];
        if (f) fd.append("avatar", f);
      }
      fd.append("nickname", nickname);
      fd.append("birthday", birthday);
      fd.append("gender", gender);
      fd.append("bio", bio);
      await api.updateProfile(fd);
      setAvatarPreview(null);
      setSuccess("资料已更新");
      setTimeout(() => setSuccess(""), 3000);
      onSaved();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="muted">加载中…</p>;

  const avatarSrc = avatarPreview || avatar;
  const initial = (nickname || "?").charAt(0).toUpperCase();

  return (
    <form className="card card-pad form-stack" onSubmit={submit}>
      {success && <div className="alert alert-success"><span>{success}</span></div>}
      {error && <div className="alert alert-danger"><span>{error}</span></div>}

      <div className="avatar-upload">
        <div className="avatar editable" onClick={() => fileRef.current?.click()} role="button">
          {avatarSrc ? <img src={avatarSrc} alt="头像" width={80} height={80} /> : <span>{initial}</span>}
          <span className="cam">✎</span>
        </div>
        <div className="au-meta">
          <span className="au-hint">点击头像更换 · 不超过 2MB</span>
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => fileRef.current?.click()}>更换头像</button>
        </div>
        <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/gif,image/webp" onChange={onAvatarChange} style={{ display: "none" }} />
      </div>

      <div className="field">
        <label className="label">昵称</label>
        <input className="input" type="text" value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={50} placeholder="设置昵称" />
      </div>
      <div className="form-grid">
        <div className="field">
          <label className="label">生日</label>
          <input className="input" type="date" value={birthday} onChange={(e) => setBirthday(e.target.value)} />
        </div>
        <div className="field">
          <label className="label">性别</label>
          <select className="select" value={gender} onChange={(e) => setGender(e.target.value)}>
            {GENDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>
      <div className="field">
        <label className="label">个人简介</label>
        <textarea className="textarea" value={bio} onChange={(e) => setBio(e.target.value)} maxLength={500} rows={3} placeholder="介绍一下自己吧" />
      </div>

      <p className="hint">
        邮件等通道通知已移至「通知」面板，可按来源逐个订阅（站内通知为基线，始终投递）。
      </p>

      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "保存中…" : "保存"}</button>
      </div>
    </form>
  );
}
