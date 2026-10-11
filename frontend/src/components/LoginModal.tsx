import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSitePolicy } from "../api/sitePolicy";
import { humanizeApiError, type ApiError } from "../api/shared";
import PasswordInput from "./PasswordInput";

type Method = "username" | "email" | "phone";

/**
 * 统一登录弹窗 —— 结构取自原型 index.html 的 #auth-modal。
 * 登录逻辑自旧 LoginPage 原样移植（用户名/邮箱 tab + api.login / loginWithEmail）。
 *
 * 显隐由 open 控制；onLoggedIn 在登录成功后由本组件触发（令 Provider 自增 nonce，
 * 受保护路由据此重新校验会话，避免同路径不重挂导致空白）。
 * 关闭行为：带 redirectTo（受保护路由触发）时关闭并回首页，避免用户停在空白受保护页；
 * 自愿打开（顶栏/「去登录」）时仅关闭，停留在当前公开页。
 */
export default function LoginModal({
  open,
  redirectTo,
  onClose,
  onLoggedIn,
}: {
  open: boolean;
  redirectTo?: string;
  onClose: () => void;
  onLoggedIn: () => void;
}) {
  const [method, setMethod] = useState<Method>("username");
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [resendEmail, setResendEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const policy = useSitePolicy();

  // Esc 关闭弹窗（与点遮罩 / 关闭按钮同语义）
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (redirectTo) navigate("/");
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, redirectTo, onClose, navigate]);

  // 登录接口的英文 error 串 → 中文（仅登录专用项；网络等其余错误按类型走 humanizeApiError）。
  const LOGIN_ERROR_ZH: Record<string, string> = {
    "Invalid credentials": "账号或密码错误，请重新输入。",
    "Invalid JSON": "请求数据格式错误，请刷新页面后重试。",
  };

  if (!open) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!account.trim() || !password) {
      setError("请填写账号与密码后再登录。");
      return;
    }
    setLoading(true);
    setResendEmail("");
    try {
      if (method === "username") await api.login(account.trim(), password);
      else await api.loginWithEmail(account.trim(), password);

      // 防假登录：登录成功后立即自检一次；若刚建的会话已被挤/未真正建立，不进入"已登录"假态
      try {
        await api.me();
      } catch (selfErr: any) {
        if (selfErr?.status === 401) {
          // 刚登录即被挤：supersede 弹窗已由 shared.ts 拦截器 + SessionGuard 触发，这里只关登录框
          onClose();
          return;
        }
        // 其它错误（网络等）：登录确已成功，乐观放行
      }

      onLoggedIn();
      onClose();
      navigate(redirectTo ?? "/");
    } catch (err: any) {
      const apiError = err?.apiError as ApiError | undefined;
      // 登录保护期：类型化结果驱动 ETA 文案（删除手写分钟换算，#16）
      if (apiError?.kind === "login_protection") {
        setError(humanizeApiError(apiError));
        return;
      }
      if (apiError?.kind === "login_throttled") {
        setError(humanizeApiError(apiError));
        return;
      }
      // 自助注册三态：账号已停用 / 邮箱未验证（后者附「重发验证邮件」入口）
      if (apiError?.kind === "account_disabled") {
        setError(humanizeApiError(apiError));
        return;
      }
      if (apiError?.kind === "email_not_verified") {
        setError(humanizeApiError(apiError));
        setResendEmail(apiError.email);
        return;
      }
      // 登录专用英文串（Invalid credentials 等）优先映射；其余按类型回退通用中文文案（#7 故事 7）。
      const raw = (err?.message as string) || "";
      setError(LOGIN_ERROR_ZH[raw] ?? humanizeApiError(apiError ?? { kind: "http", status: 0 }));
    } finally {
      setLoading(false);
    }
  };

  // 用户主动关闭（按钮 / 点遮罩）：受保护路由场景回首页，避免停在空白页
  const handleDismiss = () => {
    if (redirectTo) navigate("/");
    onClose();
  };

  const accountLabel = method === "email" ? "邮箱" : "用户名";
  const accountType = method === "email" ? "email" : "text";
  const accountPlaceholder =
    method === "email" ? "请输入邮箱" : "请输入信息组分发的用户名";

  return (
    <div
      className="modal-scrim is-open"
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-title"
      onClick={handleDismiss}
    >
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h3 id="auth-title">登录</h3>
            <p>南汇一中传媒社</p>
          </div>
          <button className="modal-close" aria-label="关闭" type="button" onClick={handleDismiss}>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>

        <form id="auth-form" className="modal-body" autoComplete="off" onSubmit={handleSubmit}>
          {error && (
            <div className="alert alert-danger" role="alert">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
              <span>{error}</span>
            </div>
          )}
          {resendEmail && (
            <div className="hint center">
              <a href="#" onClick={(e) => { e.preventDefault(); onClose(); navigate(`/verify-email-pending?email=${encodeURIComponent(resendEmail)}`); }}>重发验证邮件 →</a>
            </div>
          )}
          <div className="seg seg-sm" role="tablist" aria-label="登录方式">
            <button className="seg-btn" type="button" aria-selected={method === "username"} onClick={() => setMethod("username")}>用户名</button>
            <button className="seg-btn" type="button" aria-selected={method === "email"} onClick={() => setMethod("email")}>邮箱</button>
            <button className="seg-btn" type="button" disabled title="即将上线">手机号</button>
          </div>
          <div className="field">
            <label className="label" htmlFor="auth-account">{accountLabel}</label>
            <div className="input-affix">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="3.2" /><path d="M5 20c1-3.5 4-5 7-5s6 1.5 7 5" /></svg>
              <input className="input" id="auth-account" type={accountType} placeholder={accountPlaceholder} value={account} onChange={(e) => setAccount(e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label className="label" htmlFor="auth-password">密码</label>
            <PasswordInput id="auth-password" placeholder="请输入密码" value={password} onChange={(e) => setPassword(e.target.value)} />
            <div className="modal-row">
              <label className="check"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> 记住登录</label>
              <a href="#" onClick={(e) => { e.preventDefault(); handleDismiss(); navigate("/forgot-password"); }}>忘记密码？</a>
            </div>
          </div>
        </form>

        <div className="modal-foot">
          <button className="btn btn-primary btn-block" type="submit" form="auth-form" disabled={loading}>
            {loading ? "登录中…" : "登录"}
          </button>
          {policy.registration_enabled && (
            <p className="hint center">
              没有账号？{" "}
              <a href="#" onClick={(e) => { e.preventDefault(); onClose(); navigate("/register"); }}>注册 →</a>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
