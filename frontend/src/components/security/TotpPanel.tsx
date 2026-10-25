import { useEffect, useState, type FormEvent } from "react";

import { redirectToStepUp, stepupHeaders } from "../../api/stepup";
import { securityApi, type TotpRow } from "../../api/security";

/**
 * 滚动密钥（TOTP）面板：绑定 / 确认 / 解绑 / 恢复代码。
 * 一个账号可绑多个（每个独立 secret）；解绑最后一个时明确提示失去主要二次验证方式。
 */
export default function TotpPanel() {
  const [rows, setRows] = useState<TotpRow[] | null>(null);
  const [max, setMax] = useState(5);
  const [label, setLabel] = useState("");
  const [setup, setSetup] = useState<{ id: number; secret: string; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    securityApi
      .totpList()
      .then((d) => {
        setRows(d.results);
        setMax(d.max);
      })
      .catch(() => setRows([]));
  };

  useEffect(load, []);

  const startSetup = async () => {
    setError("");
    setNotice("");
    setCodes(null);
    try {
      const d = await securityApi.totpSetup(label.trim());
      setSetup({ id: d.id, secret: d.secret, qr: d.qr });
    } catch (e: any) {
      setError(e?.message || "生成失败，请稍后再试。");
    }
  };

  const copySecret = async () => {
    if (!setup) return;
    try {
      // 复制不带分组空格的原值：多数 Authenticator 的手动输入框不接受空格
      await navigator.clipboard.writeText(setup.secret);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("复制失败，请手动选中密钥复制。");
    }
  };

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    if (!setup) return;
    setBusy(true);
    setError("");
    try {
      const d = await securityApi.totpConfirm(setup.id, code.trim());
      setCodes(d.recovery_codes);
      setNotice("滚动密钥已启用。");
      setSetup(null);
      setCode("");
      setLabel("");
      load();
    } catch (err: any) {
      setError(err?.message || "验证码不正确。");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    setError("");
    setNotice("");
    try {
      const d = await securityApi.totpDelete(id, stepupHeaders("manage_totp"));
      setNotice(
        d.remaining === 0
          ? "已解绑最后一个滚动密钥——账号当前没有 TOTP 二次验证。"
          : "已解绑该滚动密钥。",
      );
      load();
    } catch (e: any) {
      if (e?.status === 403) {
        redirectToStepUp("manage_totp", "/security");
        return;
      }
      setError(e?.message || "解绑失败。");
    }
  };

  const regen = async () => {
    setError("");
    setNotice("");
    try {
      const d = await securityApi.recoveryCodes(stepupHeaders("manage_totp"));
      setCodes(d.codes);
    } catch (e: any) {
      if (e?.status === 403) {
        redirectToStepUp("manage_totp", "/security");
        return;
      }
      setError(e?.message || "生成失败。");
    }
  };

  return (
    <div className="sec-panel">
      {notice && <div className="alert alert-success" role="status"><span>{notice}</span></div>}
      {error && <div className="alert alert-danger" role="alert"><span>{error}</span></div>}

      <p className="muted">
        使用 Google Authenticator、Microsoft Authenticator 等应用扫描二维码。每条密钥独立生效，
        任一验证通过即可。上限 {max} 个。
      </p>

      {rows === null ? (
        <p className="muted">加载中…</p>
      ) : rows.length === 0 ? (
        <p className="muted">尚未绑定滚动密钥。</p>
      ) : (
        <ul className="sec-devices">
          {rows.map((row) => (
            <li key={row.id} className="sec-device">
              <div>
                <strong>{row.label}</strong>
                <div className="muted sec-small">绑定于 {row.created_at.slice(0, 10)}</div>
              </div>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => remove(row.id)}>
                解绑
              </button>
            </li>
          ))}
        </ul>
      )}

      {setup ? (
        <form className="sec-setup" onSubmit={confirm}>
          <img src={setup.qr} alt="TOTP 二维码" className="sec-qr" />
          <p className="muted sec-small">
            扫不上？手动输入密钥：
            <code className="sec-secret" data-testid="totp-secret">
              {setup.secret.replace(/(.{4})/g, "$1 ").trim()}
            </code>
            <button
              type="button"
              className="btn btn-secondary btn-sm sec-copy"
              onClick={copySecret}
            >
              {copied ? "已复制" : "复制"}
            </button>
          </p>
          <div className="field">
            <label className="label" htmlFor="totp-code">输入应用显示的 6 位验证码</label>
            <input
              id="totp-code"
              className="input"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              required
            />
          </div>
          <div className="sec-actions">
            <button className="btn btn-primary" type="submit" disabled={busy || code.length !== 6}>
              {busy ? "验证中…" : "确认启用"}
            </button>
            <button className="btn btn-secondary" type="button" onClick={() => setSetup(null)}>
              取消
            </button>
          </div>
        </form>
      ) : (
        <div className="sec-actions">
          <input
            className="input"
            placeholder="名称（如 iPhone / 备用机）"
            value={label}
            maxLength={64}
            onChange={(e) => setLabel(e.target.value)}
          />
          <button className="btn btn-primary" type="button" onClick={startSetup}>
            添加滚动密钥
          </button>
          <button className="btn btn-secondary" type="button" onClick={regen}>
            重新生成恢复代码
          </button>
        </div>
      )}

      {codes && (
        <div className="sec-recovery">
          <p><strong>恢复代码（只显示这一次，请立即保存）</strong></p>
          <ul className="sec-code-grid">
            {codes.map((c) => <li key={c}><code>{c}</code></li>)}
          </ul>
          <p className="muted sec-small">每张只能用一次；手机丢失时用它登录或解绑。</p>
        </div>
      )}
    </div>
  );
}
