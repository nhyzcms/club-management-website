import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import LoginModal from "./LoginModal";

interface LoginModalCtx {
  openLogin: (redirectTo?: string) => void;
  closeLogin: () => void;
  /** 登录或登出后自增；AppShell / HomePage / 受保护路由据此重新校验会话，
   *  避免「在同一页登出后不重挂导致本地 user 状态过期」的问题。 */
  authNonce: number;
  /** 通知认证态发生变化（当前仅 AppShell 登出时调用；登录由 LoginModal 经 onLoggedIn 触发）。 */
  notifyAuthChange: () => void;
}

const Ctx = createContext<LoginModalCtx | null>(null);

export function useLoginModal(): LoginModalCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLoginModal 必须在 <LoginModalProvider> 内使用");
  return v;
}

/**
 * 全局登录弹窗 Provider：挂在 <HashRouter> 内、<SessionGuard> 外，
 * 使顶栏 / 受保护路由 / 各「去登录」入口都能调用 openLogin()。
 * 渲染时机：始终挂载 <LoginModal>，由其内部据 open 决定显隐。
 */
export default function LoginModalProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [redirectTo, setRedirectTo] = useState<string | undefined>(undefined);
  const [authNonce, setAuthNonce] = useState(0);

  const openLogin = useCallback((to?: string) => {
    setRedirectTo(to);
    setOpen(true);
  }, []);
  const closeLogin = useCallback(() => setOpen(false), []);
  const notifyAuthChange = useCallback(() => setAuthNonce((n) => n + 1), []);
  // 登录成功信号：自增 authNonce（关闭弹窗与跳转仍由 LoginModal 自行处理）
  const onLoggedIn = notifyAuthChange;

  return (
    <Ctx.Provider value={{ openLogin, closeLogin, authNonce, notifyAuthChange }}>
      {children}
      <LoginModal open={open} redirectTo={redirectTo} onClose={closeLogin} onLoggedIn={onLoggedIn} />
    </Ctx.Provider>
  );
}
