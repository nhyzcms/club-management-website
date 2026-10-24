import { useEffect, useState } from "react";

import { securityApi, type LoginEventRow } from "../../api/security";

const STATUS_LABEL: Record<string, string> = {
  success: "成功",
  failed: "失败",
  blocked: "被限流",
  challenge: "待二次验证",
};

const METHOD_LABEL: Record<string, string> = {
  password: "密码",
  passkey: "通行密钥",
  totp: "滚动密钥",
  email_code: "邮箱验证码",
  question: "安全问题",
  recovery: "恢复代码",
  authcode: "认证码",
};

const FACTOR_LABEL: Record<string, string> = {
  none: "—",
  totp: "滚动密钥",
  email_code: "邮箱码",
  question: "安全问题",
  recovery: "恢复代码",
  exempt: "豁免（未绑定 2FA）",
};

const fmt = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

/** 登录记录：时间 / 设备 / 城市 / 方式 / 二次验证 / 结果（分页 20 条）。 */
export default function LoginEventsPanel() {
  const [rows, setRows] = useState<LoginEventRow[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = (target: number, append: boolean) => {
    setLoading(true);
    securityApi
      .loginEvents(target)
      .then((d) => {
        setRows((prev) => (append ? [...prev, ...d.results] : d.results));
        setCount(d.count);
        setNext(d.next);
      })
      .catch(() => {
        if (!append) setRows([]);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => load(1, false), []);

  const more = () => {
    const target = page + 1;
    setPage(target);
    load(target, true);
  };

  return (
    <div className="sec-panel">
      {loading && rows.length === 0 ? (
        <p className="muted">加载中…</p>
      ) : rows.length === 0 ? (
        <p className="muted">暂无登录记录。</p>
      ) : (
        <>
          <ul className="sec-events">
            {rows.map((row) => (
              <li key={row.id} className={`sec-event ${row.status !== "success" ? "is-bad" : ""}`}>
                <span className="sec-event-time">{fmt(row.created_at)}</span>
                <span className="sec-event-device">
                  {row.device_label}
                  {row.is_new_device && <span className="sec-badge sec-badge-warn">新设备</span>}
                </span>
                <span className="sec-event-place">
                  {row.city || row.country || "未知"} <span className="muted">· {row.ip}</span>
                </span>
                <span className="sec-event-method">
                  {METHOD_LABEL[row.method] || row.method}
                  {row.second_factor && row.second_factor !== "none" && (
                    <span className="muted"> + {FACTOR_LABEL[row.second_factor] || row.second_factor}</span>
                  )}
                </span>
                <span className={`sec-event-status ${row.status === "success" ? "is-ok" : "is-bad"}`}>
                  {STATUS_LABEL[row.status] || row.status}
                </span>
              </li>
            ))}
          </ul>
          <div className="sec-actions">
            {next && (
              <button className="btn btn-secondary btn-sm" type="button" onClick={more} disabled={loading}>
                {loading ? "加载中…" : "加载更多"}
              </button>
            )}
            <span className="muted sec-small">共 {count} 条</span>
          </div>
        </>
      )}
      <p className="muted sec-small">位置由 IP 推算，精度到城市，仅供参考。</p>
    </div>
  );
}
