import { Fragment } from "react";

interface TabDef { key: string; label: string; divider?: boolean; }
interface Props { tabs: TabDef[]; active: string; onPick: (key: string) => void; }

export default function ProfileSideNav({ tabs, active, onPick }: Props) {
  return (
    <nav className="profile-sidenav" aria-label="个人中心导航">
      {tabs.map((t) => (
        <Fragment key={t.key}>
          {t.divider && <div className="profile-nav-divider" role="separator" />}
          <button
            type="button"
            className={"profile-nav-item" + (t.key === active ? " active" : "")}
            aria-current={t.key === active ? "true" : undefined}
            onClick={() => onPick(t.key)}
          >
            {t.label}
          </button>
        </Fragment>
      ))}
    </nav>
  );
}
