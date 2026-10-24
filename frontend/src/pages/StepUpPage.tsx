import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import AppShell from "../components/AppShell";
import { useLoginModal } from "../components/LoginModalProvider";
import {
  STEPUP_SCOPE_LABELS,
  stepupApi,
  storeGrant,
  type StepupQuestion,
  type StepupStatus,
} from "../api/stepup";
import "../styles/stepup.css";

/**
 * 安全验证页（/#/verify，ADR-0026）：
 * - 带 `?action=<scope>&next=…`：为受保护操作完成「是本人」确认；通过后回跳 next（调用方重试）；
 * - 不带参数：入口总览（可查看方式状态，受保护操作会带入目标）。
 * 方式：邮箱验证码 / 安全问题；通过后 grant 存 sessionStorage（10 分钟内同 scope 复用）。
 */
export default function StepUpPage() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const { openLogin } = useLoginModal();
  const scope = search.get("action") || "";
  const next = search.get("next") || "/";
  const scopeLabel = STEPUP_SCOPE_LABELS[scope] || scope;

  const [status, setStatus] = useState<StepupStatus | null>(null);
  const [err, setErr] = useState("");
  const [method, setMethod] = useState<"email" | "question">("email");

  // 邮箱流
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  // 问题流
  const [questions, setQuestions] = useState<StepupQuestion[]>([]);
  const [picked, setPicked] = useState<StepupQuestion | null>(null);
  const [answer, setAnswer] = useState("");

  const [busy, setBusy] = useState(false);

  const loadStatus = () => {
    stepupApi
      .status()
      .then((d) => {
        setStatus(d);
        setCooldown(d.email.cooldown_remaining);
        if (!d.email.available) setMethod("question");
      })
      .catch((e: any) => {
        if (e?.status === 401) openLogin();
        else setErr(e.message || "加载失败");
      });
  };
  useEffect(loadStatus, [openLogin]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  useEffect(() => {
    if (method !== "question" || status === null) return;
    stepupApi
      .questions()
      .then((d) => {
        setQuestions(d.mine);
        setPicked(d.mine.length ? d.mine[Math.floor(Math.random() * d.mine.length)] : null);
      })
      .catch(() => setQuestions([]));
  }, [method, status]);

  const sendCode = () => {
    setSending(true);
    setErr("");
    stepupApi
      .emailSend()
      .then(() => {
        setSent(true);
        setCooldown(60);
      })
      .catch((e: any) => {
        setErr(e.message || "发送失败，请稍后重试。");
        loadStatus(); // 刷新冷却状态（后端 429 带 retry_after）
      })
      .finally(() => setSending(false));
  };

  const submit = () => {
    if (!scope) return;
    setBusy(true);
    setErr("");
    const payload: { method: "email" | "question"; scope: string; code?: string; question_id?: number; answer?: string } =
      { method, scope };
    if (method === "email") payload.code = code.trim();
    else {
      payload.question_id = picked?.id;
      payload.answer = answer;
    }
    stepupApi
      .verify(payload)
      .then((d) => {
        storeGrant(scope, d.grant);
        navigate(next || "/", { replace: true });
      })
      .catch((e: any) => setErr(e.message || "验证失败，请重试。"))
      .finally(() => setBusy(false));
  };

  const canSubmit =
    !!scope &&
    !busy &&
    (method === "email" ? code.trim().length > 0 : !!picked && answer.trim().length > 0);

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 460 }}>
          <div style={{ paddingTop: "var(--s-12)", paddingBottom: "var(--s-12)" }}>
            <div className="card card-pad">
              <h2 style={{ marginBottom: "var(--s-4)" }}>安全验证</h2>
              {scope ? (
                <p className="muted" style={{ marginBottom: "var(--s-4)" }}>
                  正在为「{scopeLabel}」完成本人确认。通过后 10 分钟内同一操作免复验。
                </p>
              ) : (
                <p className="muted" style={{ marginBottom: "var(--s-4)" }}>
                  这里用于敏感操作前的本人确认。从「修改密码 / 换绑邮箱」等操作进入时会自动带入目标。
                </p>
              )}

              {err && (
                <div className="alert alert-danger" role="alert" style={{ marginBottom: "var(--s-3)" }}>
                  <span>{err}</span>
                </div>
              )}

              {!status ? (
                <p className="muted">加载中…</p>
              ) : (
                <>
                  {status.email.available ? (
                    <div className="stepup-methods" role="tablist" aria-label="验证方式">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={method === "email"}
                        className={"stepup-method" + (method === "email" ? " is-active" : "")}
                        onClick={() => setMethod("email")}
                      >
                        邮箱验证码
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={method === "question"}
                        className={"stepup-method" + (method === "question" ? " is-active" : "")}
                        onClick={() => setMethod("question")}
                        disabled={!status.questions.configured}
                        title={!status.questions.configured ? "尚未设置安全问题" : undefined}
                      >
                        安全问题
                      </button>
                    </div>
                  ) : null}

                  {method === "email" && status.email.available && (
                    <>
                      <p className="muted">
                        验证码将发送到已认证邮箱 <strong>{status.email.address}</strong>（10 分钟内有效）。
                      </p>
                      <div className="stepup-row">
                        <input
                          className="input"
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          maxLength={6}
                          placeholder="6 位验证码"
                          value={code}
                          aria-label="验证码"
                          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                        />
                        <button
                          className="btn"
                          type="button"
                          disabled={sending || cooldown > 0}
                          onClick={sendCode}
                        >
                          {sending ? "发送中…" : cooldown > 0 ? `${cooldown}s 后可重发` : sent ? "重新发送" : "发送验证码"}
                        </button>
                      </div>
                      {sent && <p className="muted stepup-ok" role="status">验证码已发送，请查收邮件。</p>}
                    </>
                  )}

                  {method === "question" && (
                    <>
                      {status.questions.configured ? (
                        picked ? (
                          <>
                            <div className="field">
                              <label className="label">安全问题</label>
                              <p style={{ margin: 0 }}>{picked.text}</p>
                            </div>
                            <div className="field">
                              <label className="label" htmlFor="stepup-answer">答案</label>
                              <input
                                className="input"
                                id="stepup-answer"
                                value={answer}
                                autoComplete="off"
                                onChange={(e) => setAnswer(e.target.value)}
                              />
                            </div>
                          </>
                        ) : (
                          <p className="muted">正在载入题目…</p>
                        )
                      ) : (
                        <p className="muted">
                          尚未设置安全问题。
                          <a
                            href="#"
                            onClick={(e) => {
                              e.preventDefault();
                              navigate("/security?tab=questions");
                            }}
                          >
                            去账号安全中心设置
                          </a>
                          （首次设置需输入登录密码）。
                        </p>
                      )}
                    </>
                  )}

                  {scope && (
                    <button
                      className="btn btn-primary btn-block"
                      type="button"
                      style={{ marginTop: "var(--s-4)" }}
                      disabled={!canSubmit}
                      onClick={submit}
                    >
                      {busy ? "验证中…" : "完成验证并继续"}
                    </button>
                  )}

                  <p className="muted" style={{ marginTop: "var(--s-4)" }}>
                    方式状态：邮箱{status.email.available ? `（${status.email.address}）` : "（未认证）"} ·
                    安全问题{status.questions.configured ? `（已设 ${status.questions.count} 题）` : "（未设置）"}
                  </p>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
