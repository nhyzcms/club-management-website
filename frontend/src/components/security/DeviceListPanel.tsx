import { useEffect, useState } from "react";

import { redirectToStepUp, stepupHeaders } from "../../api/stepup";
import { securityApi, type DeviceRow } from "../../api/security";

const fmt = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

const place = (row: DeviceRow): string => {
  const city = row.city || row.country || "";
  return city || "未知位置";
};

/** 已登录设备：展示 + 撤销（撤销 = 吊销该设备所有会话，需要 stepup）。 */
export default function DeviceListPanel() {
  const [rows, setRows] = useState<DeviceRow[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = () => {
    securityApi
      .devices()
      .then((d) => setRows(d.results))
      .catch(() => setRows([]));
  };

  useEffect(load, []);

  const revoke = async (id: number) => {
    setError("");
    setNotice("");
    try {
      await securityApi.revokeDevice(id, stepupHeaders("manage_devices"));
      setNotice("已退出该设备。");
      load();
    } catch (e: any) {
      if (e?.status === 403) {
        redirectToStepUp("manage_devices", "/security");
        return;
      }
      setError(e?.message || "操作失败。");
    }
  };

  return (
    <div className="sec-panel">
      {notice && <div className="alert alert-success" role="status"><span>{notice}</span></div>}
      {error && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}
      {rows === null ? (
        <p className="muted">加载中…</p>
      ) : rows.length === 0 ? (
        <p className="muted">还没有设备记录。下次用浏览器登录后会出现。</p>
      ) : (
        <ul className="sec-devices">
          {rows.map((row) => (
            <li key={row.id} className="sec-device">
              <div>
                <strong>
                  {row.label}
                  {row.is_current && <span className="sec-badge">当前</span>}
                  {!row.trusted && <span className="sec-badge sec-badge-warn">未验证</span>}
                </strong>
                <div className="muted sec-small">
                  {place(row)} · 最近活跃 {fmt(row.last_seen)}
                </div>
              </div>
              {!row.is_current && (
                <button className="btn btn-secondary btn-sm" type="button" onClick={() => revoke(row.id)}>
                  退出
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="muted sec-small">
        设备是否「已验证」只取决于它是否完成过一次二次验证；清除浏览器数据会变成新设备。
      </p>
    </div>
  );
}
