import { useEffect, useState } from "react";
import { isAppShell } from "./utils/device";

// 颜色主题：浅色 / 深色 / 跟随系统。偏好存 localStorage（按设备，游客亦可用），
// 并镜像到 Django 后台约定的 `theme` 键（auto/light/dark），使 /admin/ 自动跟随。
export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

// 浏览器地址栏 / 系统 UI 主题色（meta[name=theme-color]）。
// dark 值 = oklch(0.165 0.02 255)（--bg）的 sRGB 近似；
// template.html 内联脚本有一份同步副本（无法 import），改动需两处一致。
export const THEME_COLORS: Record<ResolvedTheme, string> = {
  light: "#ffffff",
  dark: "#080f17",
};

export const STORAGE_KEY = "cobalt:theme";
// Django admin（4.2+ 自带 data-theme）读取的键，值域 auto|light|dark。
const DJANGO_THEME_KEY = "theme";

export const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "light", label: "浅色模式" },
  { value: "dark", label: "深色模式" },
  { value: "system", label: "跟随系统" },
];

type Listener = (resolved: ResolvedTheme) => void;
const listeners = new Set<Listener>();

function systemDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

export function resolveTheme(pref: ThemePreference): ResolvedTheme {
  return pref === "system" ? (systemDark() ? "dark" : "light") : pref;
}

function mirrorDjango(pref: ThemePreference) {
  try {
    localStorage.setItem(DJANGO_THEME_KEY, pref === "system" ? "auto" : pref);
  } catch {
    /* ignore */
  }
}

function apply(pref: ThemePreference) {
  const resolved = resolveTheme(pref);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", THEME_COLORS[resolved]);
  mirrorDjango(pref);
  listeners.forEach((fn) => fn(resolved));
}

const APP_MIGRATION_KEY = "cobalt:theme:app-default-v2";

/** App 壳内的一次性迁移（template.html 的内联脚本有一份等价实现，改逻辑要两处同步）。
 *
 * 旧版壳没有任何主题切换入口，localStorage 里存下来的 "light" 基本都不是用户的有意选择，
 * 因此壳内首次运行新版本时改判为「跟随系统」；迁移标记保证只做一次，
 * 用户此后主动选的浅色/深色不会被覆盖。
 */
function migrateAppDefaultOnce() {
  if (!isAppShell()) return;
  try {
    if (localStorage.getItem(APP_MIGRATION_KEY)) return;
    localStorage.setItem(APP_MIGRATION_KEY, "1");
    if (localStorage.getItem(STORAGE_KEY) === "light") {
      localStorage.setItem(STORAGE_KEY, "system");
    }
  } catch {
    /* ignore */
  }
}

export function getTheme(): ThemePreference {
  migrateAppDefaultOnce();
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* ignore */
  }
  // 没有存过偏好时的默认值：
  //  - App 壳内跟随系统（用户反馈「App 深色模式不能跟随系统」——壳的 WebView
  //    会把系统的 uiMode 反映成 prefers-color-scheme，默认 light 就永远跟不上了）；
  //  - 浏览器保持原来的浅色默认。
  return isAppShell() ? "system" : "light";
}

export function setTheme(pref: ThemePreference) {
  try {
    localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    /* ignore */
  }
  apply(pref);
}

export function subscribeTheme(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function initTheme() {
  if (typeof window.matchMedia === "function") {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (getTheme() === "system") apply("system");
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onChange);
    }
  }
  apply(getTheme());
}

export function useTheme() {
  const [pref, setPrefState] = useState<ThemePreference>(getTheme);
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(getTheme()));

  useEffect(() => {
    return subscribeTheme((res) => {
      setPrefState(getTheme());
      setResolved(res);
    });
  }, []);

  const setPref = (p: ThemePreference) => {
    setTheme(p);
    setPrefState(p);
    setResolved(resolveTheme(p));
  };

  return { pref, resolved, setPref };
}
