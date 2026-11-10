import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_COLORS, getTheme, setTheme } from "../theme";

// jsdom 不实现 matchMedia：给主题模块一个可控替身
function mockMatchMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    })),
  );
}

const themeColorMeta = () =>
  document.querySelector('meta[name="theme-color"]')?.getAttribute("content") ?? null;

describe("theme.ts 主题切换与地址栏主题色", () => {
  beforeEach(() => {
    document.head.innerHTML = '<meta name="theme-color" content="#ffffff" />';
    localStorage.clear();
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.head.innerHTML = "";
  });

  it("setTheme('dark')：data-theme 落地且 theme-color 同步为深色值", () => {
    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeColorMeta()).toBe(THEME_COLORS.dark);
  });

  it("setTheme('light')：theme-color 同步为浅色值", () => {
    setTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(themeColorMeta()).toBe(THEME_COLORS.light);
  });

  it("system 偏好命中系统深色时：解析为 dark 且 theme-color 跟随", () => {
    mockMatchMedia(true);
    setTheme("system");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(themeColorMeta()).toBe(THEME_COLORS.dark);
    expect(getTheme()).toBe("system");
  });

  it("页面无 theme-color meta 时不抛错（渐进增强）", () => {
    document.head.innerHTML = "";
    expect(() => setTheme("dark")).not.toThrow();
  });
});

describe("App 壳内的深色默认值（2026-10-17）", () => {
  const UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 NhyzClubApp/0.2.0 (Android; 2)";
  const original = window.navigator.userAgent;

  const setUA = (ua: string) =>
    Object.defineProperty(window.navigator, "userAgent", { value: ua, configurable: true });

  beforeEach(() => {
    localStorage.clear();
    mockMatchMedia(true);
  });

  afterEach(() => {
    setUA(original);
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("没有存过偏好时默认「跟随系统」（系统深色 -> dark）", () => {
    setUA(UA);
    expect(getTheme()).toBe("system");
  });

  it("旧的 light 会被一次性迁移成 system，迁移后用户再选 light 不会被改回", () => {
    setUA(UA);
    localStorage.setItem("cobalt:theme", "light");
    expect(getTheme()).toBe("system");
    setTheme("light");
    expect(getTheme()).toBe("light");
  });

  it("普通浏览器仍默认浅色（不受影响）", () => {
    setUA("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36");
    expect(getTheme()).toBe("light");
  });
});
