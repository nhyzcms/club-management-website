import { useEffect, useState } from "react";

import AppShell from "../components/AppShell";
import DeviceListPanel from "../components/security/DeviceListPanel";
import LoginEventsPanel from "../components/security/LoginEventsPanel";
import TotpPanel from "../components/security/TotpPanel";
import PasswordPanel from "../components/profile/PasswordPanel";
import SecurityPanel from "../components/profile/SecurityPanel";
import { securityApi, type SecurityOverview } from "../api/security";
import "../styles/security.css";

type RowKey = "password" | "email" | "questions" | "passkey" | "totp" | "recovery";

interface Row {
  key: RowKey;
  icon: string;
  label: string;
  status: string;
  ok: boolean;
}

/**
 * 账号与安全（设计稿 2026-10-24，参考微软安全性页）。
 * 登录方式列表 + 登录与设备；改密 / 安全问题 / 邮箱 / 登录记录统一收在这里。
 */
export default function SecurityCenterPage() {
  const [overview, setOverview] = useState<SecurityOverview | null>(null);
  const [open, setOpen] = useState<RowKey | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    securityApi
      .overview()
      .then(setOverview)
      .catch((e: any) => setError(e?.message || "加载失败"));
  };

  useEffect(load, []);

  const rows: Row[] = [
    {
      key: "password",
      icon: "🔑",
      label: "密码",
      status: overview?.password.enabled ? "已设置" : "未设置",
      ok: Boolean(overview?.password.enabled),
    },
    {
      key: "email",
      icon: "✉",
      label: "邮箱",
      status: overview?.email.bound ? overview.email.address : "未绑定",
      ok: Boolean(overview?.email.bound),
    },
    {
      key: "questions",
      icon: "🛡",
      label: "安全问题",
      status: overview?.questions.count ? `已设置 ${overview.questions.count} 题` : "未设置",
      ok: Boolean(overview?.questions.count),
    },
    {
      key: "passkey",
      icon: "🔐",
      label: "通行密钥",
      status: overview?.passkeys.count ? `${overview.passkeys.count} 个` : "待启用",
      ok: Boolean(overview?.passkeys.count),
    },
    {
      key: "totp",
      icon: "⏱",
      label: "滚动密钥",
      status: overview?.totp.count ? `${overview.totp.count} 个` : "未设置",
      ok: Boolean(overview?.totp.count),
    },
    {
      key: "recovery",
      icon: "🗝",
      label: "恢复代码",
      status: overview?.recovery.remaining ? `剩 ${overview.recovery.remaining} 个` : "未生成",
      ok: Boolean(overview?.recovery.remaining),
    },
  ];

  const toggle = (key: RowKey) => setOpen((prev) => (prev === key ? null : key));

  return (
    <AppShell>
      <div className="sec-page">
        <header className="sec-hero">
          <h1>账号与安全</h1>
          <div className="sec-quick">
            <button type="button" className="sec-quick-card" onClick={() => toggle("password")}>
              <span aria-hidden>🔑</span>
              <span>
                <strong>修改密码</strong>
                <small>更换登录密码</small>
              </span>
            </button>
            <button type="button" className="sec-quick-card" onClick={() => toggle("questions")}>
              <span aria-hidden>🛡</span>
              <span>
                <strong>二次验证</strong>
                <small>管理验证方式</small>
              </span>
            </button>
          </div>
        </header>

        {error && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}

        <section>
          <h2>证明你的身份的方法</h2>
          <p className="muted">用于登录与敏感操作。绑定得越多，找回账号越容易。</p>
          <ul className="sec-methods">
            {rows.map((row) => (
              <li key={row.key} className="sec-method-wrap">
                <button
                  type="button"
                  className={`sec-method ${open === row.key ? "is-open" : ""}`}
                  onClick={() => toggle(row.key)}
                  aria-expanded={open === row.key}
                >
                  <span className="sec-method-icon" aria-hidden>{row.icon}</span>
                  <span className="sec-method-label">{row.label}</span>
                  <span className="sec-method-status">{row.status}</span>
                  <span className={`sec-check ${row.ok ? "is-ok" : ""}`} aria-hidden>
                    {row.ok ? "✓" : "›"}
                  </span>
                </button>

                {open === row.key && (
                  <div className="sec-method-body">
                    {row.key === "password" && <PasswordPanel />}
                    {row.key === "questions" && <SecurityPanel />}
                    {row.key === "totp" && <TotpPanel />}
                    {row.key === "email" && (
                      <p className="muted">
                        邮箱用于接收验证码与安全通知。修改邮箱请到「资料编辑」页；换绑需要先完成安全验证。
                      </p>
                    )}
                    {row.key === "passkey" && (
                      <p className="muted">
                        通行密钥（Passkey）需要 HTTPS 域名才能启用，当前站点尚不满足条件；域名就绪后在此绑定。
                      </p>
                    )}
                    {row.key === "recovery" && (
                      <p className="muted">
                        恢复代码在首次绑定滚动密钥时生成，用于手机丢失时登录。需要重新生成请到「滚动密钥」面板。
                      </p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2>登录与设备</h2>
          <p className="muted">每个账号的设备都会记录；陌生设备登录需要二次验证。</p>
          <DeviceListPanel />
          <h3 className="sec-subhead">登录记录</h3>
          <LoginEventsPanel />
        </section>
      </div>
    </AppShell>
  );
}
