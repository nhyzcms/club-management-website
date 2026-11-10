import { useEffect, useState } from "react";
import { messagingApi } from "../../api/messaging";
import type { NotificationPreferences } from "../../types/messaging";

/** 通知订阅面板：源 × 通道矩阵，勾选即时保存；所有通道均可开关（用户可选择拒绝接收）。 */
export default function NotificationPreferencesPanel() {
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "ok" | "err">("idle");

  useEffect(() => {
    messagingApi.getNotificationPreferences()
      .then(setPrefs)
      .catch((e: any) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  const toggle = async (source: string, channel: string, enabled: boolean) => {
    if (!prefs) return;
    // 乐观更新，失败回滚
    setPrefs({
      ...prefs,
      sources: prefs.sources.map((s) =>
        s.key === source ? { ...s, channels: { ...s.channels, [channel]: enabled } } : s,
      ),
    });
    setSaveState("saving");
    try {
      const next = await messagingApi.updateNotificationPreferences([{ source, channel, enabled }]);
      setPrefs(next);
      setSaveState("ok");
      setTimeout(() => setSaveState("idle"), 1600);
    } catch (e: any) {
      setSaveState("err");
      setError(e?.message || "保存失败");
      messagingApi.getNotificationPreferences().then(setPrefs).catch(() => {});
    }
  };

  if (loading) return <p className="muted">加载中…</p>;
  if (!prefs) return <div className="alert alert-danger"><span>{error || "加载失败"}</span></div>;

  const emailCh = prefs.channels.find((c) => c.key === "email");
  const emailReady = !!emailCh?.available;

  return (
    <div className="card card-pad">
      <h3 style={{ marginTop: 0 }}>通知订阅</h3>
      <p className="hint">
        选择想接收的通知来源与通道。关闭某来源的站内通道后，将不再接收该来源的通知。
        {emailCh && !emailReady && " 邮件通道需先绑定邮箱（见「资料编辑」）。"}
      </p>
      {saveState === "saving" && <p className="hint" role="status">保存中…</p>}
      {saveState === "ok" && <p className="hint" role="status">已保存 ✓</p>}
      {saveState === "err" && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}

      <div className="notif-matrix">
        {prefs.sources.map((src) => (
          <div className="notif-source" key={src.key}>
            <div className="notif-source-info">
              <strong>{src.name}</strong>
              <p className="hint">{src.description}</p>
            </div>
            <div className="notif-source-channels">
              {prefs.channels.map((ch) => {
                const disabled = !ch.available;
                return (
                  <label
                    className={"check notif-ch" + (disabled ? " is-off" : "")}
                    key={ch.key}
                    title={!ch.available ? `${ch.name}通道当前不可用` : ch.description}
                  >
                    <input
                      type="checkbox"
                      checked={!!src.channels[ch.key]}
                      disabled={disabled}
                      onChange={(e) => toggle(src.key, ch.key, e.target.checked)}
                    />
                    {ch.name}
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
