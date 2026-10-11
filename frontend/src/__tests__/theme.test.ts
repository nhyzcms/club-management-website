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
