import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import ConfirmModal from "../ConfirmModal";
import "../../styles/form.css";

/**
 * 个人中心 → 登录设备（多端登录，ADR-0028）。
 *
 * 同一账号最多同时保持 3 台设备登录（网页 / 手机浏览器 / App 各一台即可）。名额满时
 * 新设备登录会自动替换「最久未使用」的那台；本面板负责查看在线设备与下线操作。
 * 服务端以 `revoked_at` 为唯一真源：`is_active` = 仍保持登录态，`is_this_device` =
 * 当前请求所属设备（由服务端比对 session key 得出，前端不猜）。
 */
interface SessionRow {
  id: number;
  device_name: string;
  device_type: string;
  client_kind: string;
  ip_address: string | null;
  created_at: string;
  last_seen_at: string | null;
  is_active: boolean;
  is_this_device: boolean;
  revoked_at: string | null;
  revoked_reason: string;
}

interface SessionsPayload {
  results: SessionRow[];
  max_active: number;
  active_count: number;
}

const DEVICE_TYPE_LABEL: Record<string, string> = {
  Desktop: "桌面端", Mobile: "手机", Tablet: "平板", Bot: "爬虫", Unknown: "未知",
};

const CLIENT_KIND_LABEL: Record<string, string> = {
  web: "网页", mobile: "手机浏览器", app: "App",
};

const REVOKE_REASON_LABEL: Record<string, string> = {
  limit: "名额已满被替换",
  manual: "手动下线",
  logout: "已退出登录",
  replaced: "设备重新登录",
  security: "安全吊销",
};

const fmt = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

const clientKind = (row: SessionRow): string =>
  CLIENT_KIND_LABEL[row.client_kind] ?? (DEVICE_TYPE_LABEL[row.device_type] ?? row.device_type);

export default function SessionsPanel() {
  const [data, setData] = useState<SessionsPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<
    { kind: "one"; row: SessionRow } | { kind: "others" } | null
  >(null);

  const load = useCallback(() => {
    api.listSessions()
      .then((d: any) => {
        setData({
          results: Array.isArray(d?.results) ? d.results : [],
          max_active: typeof d?.max_active === "number" ? d.max_active : 3,
          active_count: typeof d?.active_count === "number" ? d.active_count : 0,
        });
      })
      .catch(() => setData({ results: [], max_active: 3, active_count: 0 }));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function confirmAction() {
    if (!pending) return;
    setBusy(true);
    setError("");
    try {
      if (pending.kind === "one") {
        const res: any = await api.revokeSession(pending.row.id);
        if (res?.was_current) {
          // 下线的是本机 → 等价于退出登录，直接回首页（登录态已失效）。
          window.location.replace("/");
          return;
        }
      } else {
        await api.revokeOtherSessions();
      }
      setPending(null);
      load();
    } catch {
      setError("操作失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  const max = data?.max_active ?? 3;
  const active = (data?.results ?? []).filter((r) => r.is_active);
  const history = (data?.results ?? []).filter((r) => !r.is_active);
  const activeCount = data?.active_count ?? active.length;

  return (
    <div className="card card-pad">
      <h2 className="profile-panel-title">登录设备</h2>
      <p className="muted ps-intro">
        同一账号最多同时保持 {max} 台设备登录（网页、手机浏览器、App 各一台正好占满）。
        名额已满时，新设备登录会自动替换<strong>最久未使用</strong>的那台。
      </p>

      {data === null ? (
        <p className="muted">加载中…</p>
      ) : (
        <>
          <div className="ps-quota">
            <span className="badge badge-success">在线 {activeCount} / {max}</span>
            {active.length > 1 && (
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setPending({ kind: "others" })}
                disabled={busy}
              >
                下线其他所有设备
              </button>
            )}
          </div>

          {error && (
            <div className="alert alert-danger" role="alert" style={{ marginBottom: "var(--s-3)" }}>
              <span>{error}</span>
            </div>
          )}

          {active.length === 0 ? (
            <p className="muted">当前没有在线的设备。</p>
          ) : (
            <ul className="profile-sessions">
              {active.map((s) => (
                <li key={s.id} className="profile-session">
                  <div className="ps-main">
                    <div className="ps-name">
                      {s.device_name || "未知设备"}
                      <span className="badge badge-ghost ps-kind">{clientKind(s)}</span>
                      {s.is_this_device && <span className="badge badge-success">本机</span>}
                    </div>
                    <div className="muted ps-sub">
                      {s.ip_address ? `${s.ip_address} · ` : ""}
                      登录 {fmt(s.created_at)}
                      {s.last_seen_at ? ` · 最近活跃 ${fmt(s.last_seen_at)}` : ""}
                    </div>
                  </div>
                  {s.is_this_device ? (
                    <span className="muted ps-hint">当前设备</span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => setPending({ kind: "one", row: s })}
                      disabled={busy}
                    >
                      下线
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {history.length > 0 && (
            <details className="ps-history">
              <summary>最近下线记录（{history.length}）</summary>
              <ul className="profile-sessions">
                {history.map((s) => (
                  <li key={s.id} className="profile-session">
                    <div className="ps-main">
                      <div className="ps-name">
                        {s.device_name || "未知设备"}
                        <span className="badge badge-ghost ps-kind">{clientKind(s)}</span>
                      </div>
                      <div className="muted ps-sub">
                        {REVOKE_REASON_LABEL[s.revoked_reason] ?? "已下线"}
                        {s.revoked_at ? ` · ${fmt(s.revoked_at)}` : ""}
                        {s.ip_address ? ` · ${s.ip_address}` : ""}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      {pending && (
        <ConfirmModal
          title={pending.kind === "others" ? "下线其他所有设备？" : "下线这台设备？"}
          confirmLabel={pending.kind === "others" ? "全部下线" : "确认下线"}
          danger
          busy={busy}
          onConfirm={confirmAction}
          onCancel={() => { if (!busy) setPending(null); }}
        >
          {pending.kind === "others" ? (
            <p>其他设备会立即退出登录，本机保持在线。</p>
          ) : (
            <p>
              {pending.row.device_name || "该设备"}（{clientKind(pending.row)}）
              会立即退出登录，需要重新输入密码才能再次使用。
            </p>
          )}
        </ConfirmModal>
      )}
    </div>
  );
}
