import { useEffect, useRef, useState, ReactNode } from "react";

import { setSupersedeHandler, SupersedeTakeover } from "../api/shared";
import { api } from "../api/client";
import SessionSupersedeModal from "./SessionSupersedeModal";
import { useLoginModal } from "./LoginModalProvider";

// 轮询提速到 15s：被挤设备最迟 ~15s 感知挤号（原 60s）；内部工具并发低，15s 心跳可接受
const POLL_INTERVAL_MS = 15000;

export default function SessionGuard({ children }: { children: ReactNode }) {
  const [takeover, setTakeover] = useState<SupersedeTakeover | null>(null);
  const [revokedReason, setRevokedReason] = useState<string | undefined>(undefined);
  const intervalRef = useRef<number | null>(null);
  const { openLogin, authNonce } = useLoginModal();

  // supersede 回调：显示挤号弹窗（幂等：已显示则不覆盖）并停轮询
  useEffect(() => {
    setSupersedeHandler((result) => {
      // result 为类型化「会话被挤下线」结果（#16 / ADR-0028）；取 takeover + 下线原因渲染弹窗
      setTakeover((prev) => prev ?? result.takeover);
      setRevokedReason((prev) => prev ?? result.revokedReason);
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    });
    return () => setSupersedeHandler(null);
  }, []);

  // 仅在已登录时轮询 /auth/me/：挂载 + 每次登录/登出（authNonce 变化）后先探测一次，
  // 已登录才起 15s 心跳；未登录/已登出则不轮询——没有会话就不会被挤号。
  useEffect(() => {
    let cancelled = false;
    api.me()
      .then(() => {
        if (cancelled) return;
        intervalRef.current = window.setInterval(() => {
          api.me().catch(() => {}); // supersede 401 由 shared.ts 拦截器处理；其它错误忽略
        }, POLL_INTERVAL_MS);
      })
      .catch(() => {
        // 未登录：不轮询
      });
    return () => {
      cancelled = true;
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [authNonce]);

  function handleConfirm() {
    setTakeover(null);
    setRevokedReason(undefined);
    openLogin();
  }

  return (
    <>
      {children}
      <SessionSupersedeModal
        takeover={takeover}
        revokedReason={revokedReason}
        onConfirm={handleConfirm}
      />
    </>
  );
}
