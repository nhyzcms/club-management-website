/**
 * Cloudflare Turnstile 前端集成。
 *
 * sitekey 由 ``GET /site-policy/`` 下发。未启用时不加载 Cloudflare 脚本、不渲染挂件。
 * 脚本按需注入（注册 / 找回密码 / 重发认证信 / 匿名反馈），避免全站预载。
 */
import { useEffect, useRef, useState, type RefObject } from "react";
import { useSitePolicy, useSitePolicyReady } from "./api/sitePolicy";

const SCRIPT_ID = "cf-turnstile-api";
const SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

export interface TurnstileRenderOptions {
  sitekey: string;
  callback?: (token: string) => void;
  "error-callback"?: () => void;
  "expired-callback"?: () => void;
  theme?: "light" | "dark" | "auto";
}

declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: TurnstileRenderOptions) => string;
      reset: (widgetId?: string) => void;
      remove: (widgetId: string) => void;
    };
  }
}

function loadTurnstileScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("turnstile")), { once: true });
    });
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("turnstile"));
    document.head.appendChild(script);
  });
}

export function renderTurnstile(
  container: HTMLElement,
  sitekey: string,
  onToken: (token: string) => void,
  onError?: () => void
): string | null {
  const api = window.turnstile;
  if (!api || !sitekey) return null;
  return api.render(container, {
    sitekey,
    callback: onToken,
    "error-callback": onError,
    "expired-callback": onError,
    theme: "auto",
  });
}

export function useTurnstile(active = true): {
  containerRef: RefObject<HTMLDivElement | null>;
  token: string;
  reset: () => void;
  enabled: boolean;
  policyReady: boolean;
} {
  const policy = useSitePolicy();
  const policyReady = useSitePolicyReady();
  const enabled = Boolean(active && policy.turnstile_enabled && policy.turnstile_site_key);
  const [token, setToken] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      setToken("");
      return;
    }
    const sitekey = policy.turnstile_site_key;
    let cancelled = false;
    let poll = 0;
    let timeout = 0;

    const tryRender = () => {
      if (cancelled || widgetIdRef.current) return true;
      const container = containerRef.current;
      if (!container) return false;
      const id = renderTurnstile(container, sitekey, setToken, () => setToken(""));
      if (id) widgetIdRef.current = id;
      return !!id;
    };

    const start = () => {
      if (cancelled) return;
      if (tryRender()) return;
      poll = window.setInterval(() => {
        if (tryRender()) window.clearInterval(poll);
      }, 100);
      timeout = window.setTimeout(() => window.clearInterval(poll), 10000);
    };

    loadTurnstileScript().then(start).catch(() => {});

    return () => {
      cancelled = true;
      if (poll) window.clearInterval(poll);
      if (timeout) window.clearTimeout(timeout);
      const id = widgetIdRef.current;
      widgetIdRef.current = null;
      if (id && window.turnstile) window.turnstile.remove(id);
    };
  }, [enabled, policy.turnstile_site_key]);

  const reset = () => {
    setToken("");
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.reset(widgetIdRef.current);
    }
  };

  return { containerRef, token, reset, enabled, policyReady };
}
