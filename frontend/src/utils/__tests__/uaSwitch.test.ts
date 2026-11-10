import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { classifyUserAgent } from "../device";
import {
  UA_CLASS_STORAGE_KEY,
  applyUaSwitch,
  decideUaSwitch,
  isMobilePath,
  normalizeHashPath,
} from "../uaSwitch";

const DESKTOP_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
  + "Chrome/125.0.0.0 Safari/537.36";
const MOBILE_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
  + "Chrome/125.0.0.0 Mobile Safari/537.36";
const APP_UA =
  MOBILE_UA + " NhyzClubApp/0.2.0 (Android; 2) NhyzClubShell/0.2.0 (native; 2)";

const setUA = (ua: string) =>
  Object.defineProperty(window.navigator, "userAgent", { value: ua, configurable: true });

describe("classifyUserAgent", () => {
  it("三档分类：壳 > 手机 > 桌面", () => {
    expect(classifyUserAgent(APP_UA)).toBe("app");
    expect(classifyUserAgent(MOBILE_UA)).toBe("mobile");
    expect(classifyUserAgent(DESKTOP_UA)).toBe("desktop");
    expect(classifyUserAgent("")).toBe("desktop");
  });
});

describe("normalizeHashPath / isMobilePath", () => {
  it("去掉 #、查询串与尾部斜杠", () => {
    expect(normalizeHashPath("")).toBe("/");
    expect(normalizeHashPath("#")).toBe("/");
    expect(normalizeHashPath("#/m/news/3?x=1")).toBe("/m/news/3");
    expect(normalizeHashPath("/m/")).toBe("/m");
    expect(normalizeHashPath("m")).toBe("/m");
  });

  it("只把 /m 与 /m/... 认作手机版路由（/messages 不是）", () => {
    expect(isMobilePath("/m")).toBe(true);
    expect(isMobilePath("/m/news")).toBe(true);
    expect(isMobilePath("/messages")).toBe(false);
    expect(isMobilePath("/news")).toBe(false);
  });
});

describe("decideUaSwitch", () => {
  it("首次访问（无记录）不跳转", () => {
    expect(decideUaSwitch(null, "mobile", "#/")).toBeNull();
    expect(decideUaSwitch(null, "desktop", "#/m/news")).toBeNull();
  });

  it("类别没变时保持原地址（含深链接）", () => {
    expect(decideUaSwitch("desktop", "desktop", "#/news/42")).toBeNull();
    expect(decideUaSwitch("mobile", "mobile", "#/m/news/42")).toBeNull();
  });

  it("App 壳 ↔ 手机浏览器同属移动侧，不跳", () => {
    expect(decideUaSwitch("mobile", "app", "#/m/news/42")).toBeNull();
    expect(decideUaSwitch("app", "mobile", "#/m/me")).toBeNull();
  });

  it("桌面 → 移动：映射到手机版等价页，无等价则落到手机版首页", () => {
    expect(decideUaSwitch("desktop", "mobile", "#/")).toBe("/m");
    expect(decideUaSwitch("desktop", "mobile", "#/news")).toBe("/m/news");
    expect(decideUaSwitch("desktop", "mobile", "#/news/42")).toBe("/m/news/42");
    expect(decideUaSwitch("desktop", "app", "#/activity/7")).toBe("/m/activity/7");
    expect(decideUaSwitch("desktop", "mobile", "#/tutorials/9")).toBe("/m/tutorials/9");
    expect(decideUaSwitch("desktop", "mobile", "#/join/form")).toBe("/m/join/form");
    expect(decideUaSwitch("desktop", "mobile", "#/profile")).toBe("/m/me");
    expect(decideUaSwitch("desktop", "mobile", "#/messages")).toBe("/m");
    expect(decideUaSwitch("desktop", "mobile", "#/news/42/edit")).toBe("/m");
    // 手机版工作台：桌面 → 手机
    expect(decideUaSwitch("desktop", "mobile", "#/reviews")).toBe("/m/review");
    expect(decideUaSwitch("desktop", "mobile", "#/inbox")).toBe("/m/inbox");
    expect(decideUaSwitch("desktop", "mobile", "#/notifications")).toBe("/m/notifications");
    expect(decideUaSwitch("desktop", "mobile", "#/tasks")).toBe("/m/tasks");
    expect(decideUaSwitch("desktop", "mobile", "#/tasks/12")).toBe("/m/tasks/12");
    // 桌面新建任务表单没有手机版，回落首页而不是造一个不存在的 /m/tasks/new
    expect(decideUaSwitch("desktop", "mobile", "#/tasks/new")).toBe("/m");
  });

  it("移动 → 桌面：映射回桌面版等价页", () => {
    expect(decideUaSwitch("mobile", "desktop", "#/m")).toBe("/");
    expect(decideUaSwitch("mobile", "desktop", "#/m/news")).toBe("/news");
    expect(decideUaSwitch("mobile", "desktop", "#/m/news/42")).toBe("/news/42");
    expect(decideUaSwitch("app", "desktop", "#/m/activity/7")).toBe("/activity/7");
    expect(decideUaSwitch("mobile", "desktop", "#/m/me")).toBe("/profile");
    expect(decideUaSwitch("mobile", "desktop", "#/m/unknown")).toBe("/");
    // 手机版工作台：手机 → 桌面
    expect(decideUaSwitch("mobile", "desktop", "#/m/review")).toBe("/reviews");
    expect(decideUaSwitch("mobile", "desktop", "#/m/tasks/12")).toBe("/tasks/12");
  });

  it("已经在目标侧就不跳（避免多此一举）", () => {
    expect(decideUaSwitch("desktop", "mobile", "#/m/news/42")).toBeNull();
    expect(decideUaSwitch("mobile", "desktop", "#/news/42")).toBeNull();
  });
});

describe("applyUaSwitch", () => {
  const originalUa = window.navigator.userAgent;

  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    setUA(DESKTOP_UA);
  });

  afterEach(() => {
    setUA(originalUa);
    window.history.replaceState(null, "", "/");
  });

  it("首次访问只记录类别，不动地址", () => {
    window.history.replaceState(null, "", "/#/news/42");
    expect(applyUaSwitch()).toBeNull();
    expect(localStorage.getItem(UA_CLASS_STORAGE_KEY)).toBe("desktop");
    expect(window.location.hash).toBe("#/news/42");
  });

  it("桌面 → 手机：改写到手机版等价页并记录新类别", () => {
    localStorage.setItem(UA_CLASS_STORAGE_KEY, "desktop");
    window.history.replaceState(null, "", "/#/news/42");
    setUA(APP_UA);

    expect(applyUaSwitch()).toBe("/m/news/42");
    expect(window.location.hash).toBe("#/m/news/42");
    expect(localStorage.getItem(UA_CLASS_STORAGE_KEY)).toBe("app");
  });

  it("手机 → 桌面：改写到桌面版等价页", () => {
    localStorage.setItem(UA_CLASS_STORAGE_KEY, "mobile");
    window.history.replaceState(null, "", "/#/m/me");
    setUA(DESKTOP_UA);

    expect(applyUaSwitch()).toBe("/profile");
    expect(window.location.hash).toBe("#/profile");
    expect(localStorage.getItem(UA_CLASS_STORAGE_KEY)).toBe("desktop");
  });

  it("只跳一次：同一 UA 再刷新不再改写地址", () => {
    localStorage.setItem(UA_CLASS_STORAGE_KEY, "desktop");
    window.history.replaceState(null, "", "/#/news");
    setUA(MOBILE_UA);
    expect(applyUaSwitch()).toBe("/m/news");

    // 模拟再次刷新：UA 与记录一致
    expect(applyUaSwitch()).toBeNull();
    expect(window.location.hash).toBe("#/m/news");
  });

  it("localStorage 里的脏值按「无记录」处理", () => {
    localStorage.setItem(UA_CLASS_STORAGE_KEY, "ipad");
    window.history.replaceState(null, "", "/#/m/news");
    setUA(DESKTOP_UA);

    expect(applyUaSwitch()).toBeNull();
    expect(window.location.hash).toBe("#/m/news");
    expect(localStorage.getItem(UA_CLASS_STORAGE_KEY)).toBe("desktop");
  });
});
