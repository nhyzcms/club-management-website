import { useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { redirectToStepUp, stepupHeaders } from "../../api/stepup";
import PasswordInput from "../PasswordInput";
import "../../styles/form.css";

const CONFIRM_PHRASE = "注销账号";

/**
 * 账号注销（ADR-0027）。
 *
 * 三重确认，全部由后端复核（前端只负责可读性）：
 * 1. 勾选「已了解后果」；
 * 2. 逐字输入「注销账号」；
 * 3. 当前密码；账号配置了安全验证方式（认证邮箱 / 安全问题）时还需 Step-up grant——
 *    缺 grant 后端回 403 `step_up_required`，这里跳验证页，完成即回本页重试。
 *
 * 成功后账号立即登出，`window.location.replace("/")` 清掉 SPA 里的登录态。
 */
export default function AccountDeletionPanel() {
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [ack, setAck] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  const canSubmit = ack && confirmText.trim() === CONFIRM_PHRASE && password.length > 0 && !busy;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!ack) { setError("请先勾选「我已了解注销后果」。"); return; }
    if (confirmText.trim() !== CONFIRM_PHRASE) {
      setError(`请完整输入「${CONFIRM_PHRASE}」以确认。`);
      return;
    }
    if (!password) {
      setError("请输入当前密码。");
      passwordRef.current?.focus();
      return;
    }

    setBusy(true);
    try {
      await api.deleteAccount(password, stepupHeaders("delete_account"));
      // 服务端已注销并登出：整页跳回首页，避免 SPA 内存里残留登录态。
      window.location.replace("/");
    } catch (err: any) {
      if (err?.status === 403) {
        // 需要安全验证：验证完成后回到本面板重试。
        setBusy(false);
        redirectToStepUp("delete_account", "/profile?tab=delete");
        return;
      }
      setError(err?.message || "注销失败，请稍后重试。");
      setBusy(false);
    }
  };

  return (
    <div className="card card-pad danger-zone">
      <h2 className="danger-zone-title">注销账号</h2>
      <p className="danger-zone-lead">
        注销后账号<b>无法恢复</b>，请先确认已无未完成的事项。注销将立即执行以下处理：
      </p>
      <ul className="danger-zone-list">
        <li>删除登录邮箱、头像、生日、性别、简介，以及身份证明等上传材料；</li>
        <li>退出所有设备并停用账号，之后无法再登录、发私信或被 @ 提及；</li>
        <li>历史私信、评论与发布内容仍保留，展示为「该用户已注销」；</li>
        <li>后台仍保留账号编号、社员编号与真实姓名等基本信息，用于审计与名册核对。</li>
      </ul>

      <form className="form-stack" onSubmit={submit}>
        {error && (
          <div className="alert alert-danger" role="alert">
            <span>{error}</span>
          </div>
        )}

        <div className="field">
          <label className="label" htmlFor="delete-account-password">当前密码</label>
          <PasswordInput
            id="delete-account-password"
            ref={passwordRef}
            name="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </div>

        <div className="field">
          <label className="label" htmlFor="delete-account-confirm">
            输入「{CONFIRM_PHRASE}」以确认
          </label>
          <input
            id="delete-account-confirm"
            className="input"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={CONFIRM_PHRASE}
            autoComplete="off"
            required
          />
        </div>

        <label className="danger-zone-ack">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>我已了解注销后果，且确认这是本人操作。</span>
        </label>

        <div className="form-actions">
          <button className="btn btn-danger" type="submit" disabled={!canSubmit}>
            {busy ? "注销中…" : "永久注销账号"}
          </button>
        </div>
      </form>
    </div>
  );
}
