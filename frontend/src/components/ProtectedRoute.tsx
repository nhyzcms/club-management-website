import { useState, useEffect, ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useLoginModal } from "./LoginModalProvider";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const { openLogin, authNonce } = useLoginModal();
  const location = useLocation();

  // 初次 + 每次认证态变化（登录/登出，authNonce 变化）后重新校验会话
  useEffect(() => {
    setLoading(true);
    api.me()
      .then(() => setAuthenticated(true))
      .catch(() => setAuthenticated(false))
      .finally(() => setLoading(false));
  }, [authNonce]);

  // 未认证：打开登录弹窗（带回跳地址），并渲染 null（弹窗遮罩在前）
  useEffect(() => {
    if (!loading && !authenticated) {
      openLogin(location.pathname + location.search);
    }
  }, [loading, authenticated, openLogin, location]);

  if (loading || !authenticated) return null;
  return <>{children}</>;
}
