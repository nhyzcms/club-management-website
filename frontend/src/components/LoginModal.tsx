import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSitePolicy } from "../api/sitePolicy";
import { humanizeApiError, type ApiError } from "../api/shared";
import PasswordInput from "./PasswordInput";

type Method = "username" | "email" | "phone";

const FACTOR_LABELS: Record<string, string> = {
  totp: "滚动密钥",
  email_code: "邮箱验证码",
  question: "安全问题",
  recovery: "恢复代码",
};

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
  // 桌面默认不勾（公共设备安全）；移动端默认勾选——微信内置浏览器常被系统杀进程，
  // 不勾会频繁要求重新登录。
  const [remember, setRemember] = useState(
    () => typeof navigator !== "undefined" && /Mobile|Android|iPhone|iPad/i.test(navigator.userAgent),
  );
  // 陌生设备二次验证（P3）：登录接口回 202 + challenge
  const [challenge, setChallenge] = useState<{
    token: string;
    methods: string[];
    questions: { id: number; text: string }[];
  } | null>(null);
  const [chMethod, setChMethod] = useState("");
  const [chCode, setChCode] = useState("");
  const [chQuestionId, setChQuestionId] = useState(0);
  const [chAnswer, setChAnswer] = useState("");
  const [chNotice, setChNotice] = useState("");
  const [chBusy, setChBusy] = useState(false);
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

  /** 登录成功后的统一收尾（含强制改密与假登录自检）。 */
  const finishLogin = async (result: any) => {
    if (result?.must_change_password) {
      onLoggedIn();
      onClose();
      navigate("/change-password-required");
      return;
    }
    // 陌生设备 + 没有任何二次验证：本次豁免放行，但必须尽快绑定
    if (result?.must_bind_2fa) {
      onLoggedIn();
      onClose();
      navigate("/security?bind=1");
      return;
    }
    try {
      await api.me();
    } catch (selfErr: any) {
      if (selfErr?.status === 401) {
        onClose();
        return;
      }
    }
    onLoggedIn();
    onClose();
    navigate(redirectTo ?? "/");
  };

  const submitChallenge = async (e: FormEvent) => {
    e.preventDefault();
    if (!challenge) return;
    setChBusy(true);
    setError("");
    setChNotice("");
    try {
      const payload: Record<string, unknown> = { token: challenge.token, method: chMethod };
      if (chMethod === "question") {
        payload.question_id = chQuestionId;
        payload.answer = chAnswer;
      } else {
        payload.code = chCode.trim();
      }
      const result = await api.challengeVerify(payload);
      setChallenge(null);
      await finishLogin(result);
    } catch (err: any) {
      setError(err?.message || "验证未通过，请重试。");
    } finally {
      setChBusy(false);
    }
  };

  const sendCode = async () => {
    if (!challenge) return;
    setChBusy(true);
    setError("");
    setChNotice("");
    try {
      await api.challengeSend(challenge.token);
      setChNotice("验证码已发送，请查收邮件。");
    } catch (err: any) {
      setError(err?.message || "发送失败，请稍后再试。");
    } finally {
      setChBusy(false);
    }
  };

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
      const result: any =
        method === "username"
          ? await api.login(account.trim(), password, remember)
          : await api.loginWithEmail(account.trim(), password, remember);

      // 陌生设备：拿到 202 挑战，切到二次验证界面
      if (result?.reason === "new_device" && result?.challenge) {
        setChallenge({
          token: result.challenge,
          methods: result.methods || [],
          questions: result.questions || [],
        });
        setChMethod((result.methods || [])[0] || "");
        setChCode("");
        setChAnswer("");
        setChQuestionId(result.questions?.[0]?.id ?? 0);
        setChNotice("");
        return;
      }

      await finishLogin(result);
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
      // 自助注册三态：账号已停用 / 邮箱未认证（后者附「重发认证邮件」入口）
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

  // 陌生设备：密码已通过，先完成一次二次验证（通过后这台设备才算已知）
  if (challenge) {
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
              <h3 id="auth-title">新设备验证</h3>
              <p>南汇一中传媒社</p>
            </div>
            <button className="modal-close" aria-label="关闭" type="button" onClick={handleDismiss}>×</button>
          </div>
          <form className="modal-body" onSubmit={submitChallenge}>
            {error && (
              <div className="alert alert-danger" role="alert"><span>{error}</span></div>
            )}
            <p className="muted">
              这台设备还没有通过过二次验证。完成一次验证后，以后在这台设备登录就不用再验。
            </p>
            <div className="seg seg-sm" role="tablist" aria-label="验证方式">
              {challenge.methods.map((m) => (
                <button
                  key={m}
                  className="seg-btn"
                  type="button"
                  aria-selected={chMethod === m}
                  onClick={() => { setChMethod(m); setError(""); setChNotice(""); }}
                >
                  {FACTOR_LABELS[m] || m}
                </button>
              ))}
            </div>
            {chMethod === "email_code" && (
              <div className="sec-actions">
                <button className="btn btn-secondary" type="button" onClick={sendCode} disabled={chBusy}>
                  发送验证码
                </button>
                {chNotice && <span className="muted">{chNotice}</span>}
              </div>
            )}
            {chMethod === "question" ? (
              <>
                <div className="field">
                  <label className="label" htmlFor="ch-question">安全问题</label>
                  <select
                    id="ch-question"
                    className="input"
                    value={chQuestionId}
                    onChange={(e) => setChQuestionId(Number(e.target.value))}
                  >
                    {challenge.questions.map((q) => (
                      <option key={q.id} value={q.id}>{q.text}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label className="label" htmlFor="ch-answer">答案</label>
                  <input
                    id="ch-answer"
                    className="input"
                    value={chAnswer}
                    onChange={(e) => setChAnswer(e.target.value)}
                    autoComplete="off"
                  />
                </div>
              </>
            ) : (
              <div className="field">
                <label className="label" htmlFor="ch-code">
                  {chMethod === "recovery" ? "恢复代码" : "验证码"}
                </label>
                <input
                  id="ch-code"
                  className="input"
                  value={chCode}
                  onChange={(e) => setChCode(e.target.value)}
                  inputMode={chMethod === "recovery" ? "text" : "numeric"}
                  autoComplete="one-time-code"
                />
              </div>
            )}
            <button className="btn btn-primary btn-block" type="submit" disabled={chBusy}>
              {chBusy ? "验证中…" : "验证并登录"}
            </button>
          </form>
        </div>
      </div>
    );
  }

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

        <form id="auth-form" className="modal-body" onSubmit={handleSubmit}>
          {error && (
            <div className="alert alert-danger" role="alert">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg>
              <span>{error}</span>
            </div>
          )}
          {resendEmail && (
            <div className="hint center">
              <a href="#" onClick={(e) => { e.preventDefault(); onClose(); navigate(`/verify-email-pending?email=${encodeURIComponent(resendEmail)}`); }}>重发认证邮件 →</a>
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
              <input className="input" id="auth-account" name="username" type={accountType} placeholder={accountPlaceholder} value={account} onChange={(e) => setAccount(e.target.value)} autoComplete="username" spellCheck={false} />
            </div>
          </div>
          <div className="field">
            <label className="label" htmlFor="auth-password">密码</label>
            <PasswordInput id="auth-password" name="password" placeholder="请输入密码" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
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
