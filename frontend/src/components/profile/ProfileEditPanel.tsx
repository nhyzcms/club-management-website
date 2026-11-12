import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../../api/client";
import { CARD_NO_IDENTITIES } from "../../types/profile";
import "../../styles/form.css";

const GENDER_OPTIONS = [
  { value: "", label: "未设置" },
  { value: "M", label: "男" },
  { value: "F", label: "女" },
  { value: "O", label: "其他" },
];

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso.slice(0, 10) : date.toLocaleDateString("zh-CN");
}

/** 资料编辑面板（仅自己可用）。保存成功后调 onSaved，由父组件刷新 Hero + 顶栏。 */
export default function ProfileEditPanel({ onSaved }: { onSaved: () => void }) {
  const [nickname, setNickname] = useState("");
  const [birthday, setBirthday] = useState("");
  const [gender, setGender] = useState("");
  const [bio, setBio] = useState("");
  const [avatar, setAvatar] = useState<string | null>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  // 实名资料（2026-11-11）：姓名每个自然年可自助改一次（改后本年置灰）；校牌号只能从空补录。
  const [realName, setRealName] = useState("");
  const [realNameEditable, setRealNameEditable] = useState(false);
  const [realNameLockedUntil, setRealNameLockedUntil] = useState<string | null>(null);
  const [identity, setIdentity] = useState("");
  const [cardNo, setCardNo] = useState("");
  const [cardNoEditable, setCardNoEditable] = useState(false);
  const [cardNoLockedReason, setCardNoLockedReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const originalRealName = useRef("");

  const applyProfile = (p: any) => {
    setNickname(p.nickname ?? "");
    setBirthday(p.birthday || "");
    setGender(p.gender ?? "");
    setBio(p.bio ?? "");
    setAvatar(p.avatar ?? null);
    setRealName(p.real_name ?? "");
    setRealNameEditable(!!p.real_name_editable);
    setRealNameLockedUntil(p.real_name_locked_until ?? null);
    setIdentity(p.identity ?? "");
    setCardNo(p.card_no ?? "");
    setCardNoEditable(!!p.card_no_editable);
    setCardNoLockedReason(p.card_no_locked_reason ?? "");
    originalRealName.current = p.real_name ?? "";
  };

  useEffect(() => {
    api.getProfile()
      .then((d: any) => applyProfile(d.profile))
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
    setError("");
    const nextName = realName.trim();
    if (realNameEditable && nextName !== originalRealName.current.trim()) {
      const ok = window.confirm(
        "真实姓名每个自然年只能修改一次，提交后本年不可再改。确认提交吗？",
      );
      if (!ok) return;
    }
    setSaving(true);
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
      if (realNameEditable && nextName) fd.append("real_name", nextName);
      if (cardNoEditable && cardNo.trim()) fd.append("card_no", cardNo.trim());
      const data: any = await api.updateProfile(fd);
      if (data?.profile) applyProfile(data.profile);
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
  const showCardNo = !identity || CARD_NO_IDENTITIES.includes(identity);

  const realNameField = (
    <div className="field">
      <label className="label" htmlFor="pe-real-name">真实姓名</label>
      <input
        className="input"
        id="pe-real-name"
        name="real_name"
        type="text"
        value={realName}
        onChange={(e) => setRealName(e.target.value)}
        maxLength={100}
        disabled={!realNameEditable}
        placeholder="填写真实姓名，用于匹配社员名册"
        autoComplete="name"
      />
      <p className="hint">
        {realNameEditable
          ? (realName
            ? "本年度还有一次修改机会，提交后需等到下一年方可再改。"
            : "填写后与社员名册配对；每个自然年只能修改一次，请核对后提交。")
          : `真实姓名已登记，${formatDate(realNameLockedUntil)} 后可自行修改；如需更正请联系管理员。`}
      </p>
    </div>
  );

  const cardNoField = (
    <div className="field">
      <label className="label" htmlFor="pe-card-no">校牌号</label>
      <input
        className="input"
        id="pe-card-no"
        name="card_no"
        type="text"
        value={cardNo}
        onChange={(e) => setCardNo(e.target.value)}
        maxLength={20}
        disabled={!cardNoEditable}
        placeholder="选填"
        autoComplete="off"
      />
      <p className="hint">
        {cardNoEditable
          ? "选填；与真实姓名一起用于匹配社员名册，登记后不可自行修改。"
          : (cardNoLockedReason === "member"
            ? "校牌号以社员名册为准，如需更正请联系管理员。"
            : "校牌号已登记，如需更正请联系管理员。")}
      </p>
    </div>
  );

  const identityFields: ReactNode = showCardNo ? (
    <div className="form-grid">{realNameField}{cardNoField}</div>
  ) : realNameField;

  return (
    <form className="card card-pad form-stack" onSubmit={submit}>
      {success && <div className="alert alert-success" role="status"><span>{success}</span></div>}
      {error && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}

      <div className="avatar-upload">
        <div className="avatar editable" onClick={() => fileRef.current?.click()} role="button" tabIndex={0} aria-label="更换头像" onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileRef.current?.click(); } }}>
          {avatarSrc ? <img src={avatarSrc} alt="头像" width={80} height={80} /> : <span>{initial}</span>}
          <span className="cam">✎</span>
        </div>
        <div className="au-meta">
          <span className="au-hint">点击头像更换 · 不超过 2MB</span>
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => fileRef.current?.click()}>更换头像</button>
        </div>
        <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/gif,image/webp" onChange={onAvatarChange} style={{ display: "none" }} />
      </div>

      {identityFields}

      <div className="field">
        <label className="label" htmlFor="pe-nickname">昵称</label>
        <input className="input" id="pe-nickname" name="nickname" type="text" value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={50} placeholder="设置昵称" autoComplete="nickname" />
      </div>
      <div className="form-grid">
        <div className="field">
          <label className="label" htmlFor="pe-bday">生日</label>
          <input className="input" id="pe-bday" name="bday" type="date" value={birthday} onChange={(e) => setBirthday(e.target.value)} autoComplete="bday" />
        </div>
        <div className="field">
          <label className="label" htmlFor="pe-gender">性别</label>
          <select className="select" id="pe-gender" name="gender" value={gender} onChange={(e) => setGender(e.target.value)}>
            {GENDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>
      <div className="field">
        <label className="label" htmlFor="pe-bio">个人简介</label>
        <textarea className="textarea" id="pe-bio" name="bio" value={bio} onChange={(e) => setBio(e.target.value)} maxLength={500} rows={3} placeholder="介绍一下自己吧" />
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
