interface TabDef { key: string; label: string; }
interface Props { tabs: TabDef[]; active: string; onPick: (key: string) => void; }

export default function ProfileTabs({ tabs, active, onPick }: Props) {
  return (
    <nav className="profile-tabs" aria-label="个人中心导航">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          className={"profile-tab" + (t.key === active ? " active" : "")}
          aria-current={t.key === active ? "true" : undefined}
          onClick={() => onPick(t.key)}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}
