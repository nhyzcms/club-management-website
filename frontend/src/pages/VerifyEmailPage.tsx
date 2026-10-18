import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import AppShell from "../components/AppShell";
import { useLoginModal } from "../components/LoginModalProvider";

/**
 * 邮箱认证页（#29）：点邮件链接落地（#/verify-email?uid=&token=）。
 * 镜像 ResetPasswordPage：挂载即调 verify 接口，显成功 / 失败，失败可去重发。
 */
export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const uid = searchParams.get("uid") || "";
  const token = searchParams.get("token") || "";
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const navigate = useNavigate();
  const { openLogin } = useLoginModal();

  useEffect(() => {
    if (!uid || !token) {
      setStatus("error");
      return;
    }
    let cancelled = false;
    api
      .verifyEmail(uid, token)
      .then(() => {
        if (!cancelled) setStatus("success");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [uid, token]);

  const goLogin = () => {
    navigate("/");
    openLogin();
  };

  return (
    <AppShell>
      <div className="page">
        <div className="container" style={{ maxWidth: 440 }}>
          <div style={{ paddingTop: "var(--s-16)", paddingBottom: "var(--s-16)" }}>
            <div className="card card-pad">
              {status === "loading" && (
                <>
                  <h2 style={{ marginBottom: "var(--s-4)" }}>正在认证邮箱…</h2>
                  <p className="muted">请稍候。</p>
                </>
              )}
              {status === "success" && (
                <>
                  <h2 style={{ marginBottom: "var(--s-4)" }}>邮箱认证成功</h2>
                  <p className="muted" style={{ marginBottom: "var(--s-5)" }}>
                    你的邮箱已认证，现在可以登录了。
                  </p>
                  <button className="btn btn-primary btn-block" type="button" onClick={goLogin}>
                    去登录
                  </button>
                </>
              )}
              {status === "error" && (
                <>
                  <h2 style={{ marginBottom: "var(--s-4)" }}>认证失败</h2>
                  <p className="muted" style={{ marginBottom: "var(--s-5)" }}>
                    该认证链接无效或已过期。可以重新发送一封认证邮件。
                  </p>
                  <button
                    className="btn btn-primary btn-block"
                    type="button"
                    onClick={() => navigate("/verify-email-pending")}
                  >
                    重新发送认证邮件
                  </button>
                  <div className="hint center" style={{ marginTop: "var(--s-4)" }}>
                    <a href="#" onClick={(e) => { e.preventDefault(); goLogin(); }}>返回登录</a>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
