import type { UserProfileData } from "../../types/profile";
import { ROLE_BADGE } from "../../types/profile";

interface Props {
  profile: UserProfileData;
  /** 自己看自己时传入（跳到资料编辑 tab）；别人看时为 undefined */
  onEdit?: () => void;
}

export default function ProfileHero({ profile, onEdit }: Props) {
  const { user, profile: p, role } = profile;
  const name = p.nickname || user.username;
  const initial = name.charAt(0).toUpperCase();
  const d = new Date(user.date_joined);
  const joined = isNaN(d.getTime())
    ? ""
    : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  return (
    <section className="profile-hero">
      <div className="profile-hero-cover" />
      <div className="profile-hero-body container">
        <div className="profile-hero-avatar">
          {p.avatar ? <img src={p.avatar} alt="" width={96} height={96} /> : <span>{initial}</span>}
        </div>
        <div className="profile-hero-meta">
          <h1 className="profile-hero-name">
            {name}
            <span className={`profile-role-badge ${ROLE_BADGE[role.variant]}`}>{role.label}</span>
          </h1>
          {joined && <p className="profile-hero-sub">注册于 {joined}</p>}
          <p className={"profile-hero-bio" + (p.bio ? "" : " muted")}>{p.bio || "这个人很懒，什么都没有写……"}</p>
        </div>
        {onEdit && <button className="btn btn-primary btn-sm profile-hero-edit" onClick={onEdit}>编辑资料</button>}
      </div>
    </section>
  );
}
