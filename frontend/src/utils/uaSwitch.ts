/** 每次加载页面（含刷新）对比「上一次的 UA 类别」，类别变了就把用户带到对应版本。
 *
 * 背景：站点是单页应用，手机版（/#/m/...）与桌面版（/#/...）是两套并列的页面，
 * 目前只在「首次访问根路径」时按 UA 分流一次（App.tsx 的 HomeRoute）。如果同一个
 * 浏览器后来改了 UA —— 手机浏览器切换「请求桌面站点」、关闭/开启、开发者工具的
 * 设备模拟、自家 App 壳与手机浏览器交替打开 —— 刷新后会停在旧的那一套页面上。
 *
 * 做法：读取当前 UA 类别，与 localStorage 里的上一次类别比较，
 * **只在跨「移动侧 / 桌面侧」变化时**跳转一次：
 *   - 变成移动侧（手机浏览器或 App 壳）→ 跳到手机版等价页；
 *   - 变成桌面侧 → 跳到桌面版等价页。
 * 只比类别、不比 UA 字符串，所以浏览器版本号变化、壳的内嵌版本号升级都不会误跳；
 * 类别没变时完全不动 URL，深链接保持原样。
 *
 * 调用时机：React 渲染之前（frontend/src/index.tsx 顶层），用 history.replaceState
 * 直接改 hash（不新增历史记录），因此不会先渲染旧页面再跳、也就没有闪屏。
 * UA 在页面生命周期内不会变，所以不需要监听事件，每次刷新跑一次即可。
 */
import { currentUaClass, isMobileUaClass, isUaClass, type UaClass } from "./device";

export const UA_CLASS_STORAGE_KEY = "cobalt:ua-class";

const MOBILE_ENTRY = "/m";
const DESKTOP_ENTRY = "/";

/** 静态路由：桌面版 → 手机版（两边都有对应页面时才列在这里）。 */
const TO_MOBILE: Record<string, string> = {
  "/": "/m",
  "/news": "/m/news",
  "/activity": "/m/activity",
  "/tutorials": "/m/tutorials",
  "/join": "/m/join",
  "/join/form": "/m/join/form",
  "/profile": "/m/me",
};

/** 静态路由：手机版 → 桌面版（TO_MOBILE 的逆映射）。 */
const TO_DESKTOP: Record<string, string> = {
  "/m": "/",
  "/m/news": "/news",
  "/m/activity": "/activity",
  "/m/tutorials": "/tutorials",
  "/m/join": "/join",
  "/m/join/form": "/join/form",
  "/m/me": "/profile",
};

/** 有移动版详情页的模块：/news/:id ↔ /m/news/:id。 */
const DETAIL_MODULES = ["news", "activity", "tutorials"];

/** 把 location.hash（如 "#/m/news/3?x=1"）归一成路由路径（"/m/news/3"）。 */
export function normalizeHashPath(raw: string): string {
  let path = (raw || "").trim();
  if (path.startsWith("#")) path = path.slice(1);
  path = path.split("?")[0].split("#")[0];
  if (!path.startsWith("/")) path = `/${path}`;
  const trimmed = path.replace(/\/+$/, "");
  return trimmed === "" ? "/" : trimmed;
}

/** 是否手机版路由（/m 或 /m/...）。
 *
 * 不能写成 startsWith("/m")：/messages 会被误判成手机版页面。
 */
export function isMobilePath(path: string): boolean {
  return path === "/m" || path.startsWith("/m/");
}

function detailTarget(segments: string[], prefix: string): string | null {
  if (segments.length !== 2 || segments[1] === "") return null;
  if (!DETAIL_MODULES.includes(segments[0])) return null;
  return `${prefix}${segments[0]}/${segments[1]}`;
}

function desktopToMobile(path: string): string {
  const mapped = TO_MOBILE[path];
  if (mapped) return mapped;
  return detailTarget(path.slice(1).split("/"), "/m/") ?? MOBILE_ENTRY;
}

function mobileToDesktop(path: string): string {
  const mapped = TO_DESKTOP[path];
  if (mapped) return mapped;
  return detailTarget(path.slice(3).split("/"), "/") ?? DESKTOP_ENTRY;
}

/** 纯函数：给出本次加载需要跳转到的路径；无需跳转返回 null。
 *
 * - previous 为 null（该浏览器第一次访问、或清过 localStorage）时只记录不跳，
 *   保持原来的行为（根路径由 HomeRoute 分流，深链接不动）。
 * - App 壳 ↔ 手机浏览器同属移动侧，页面一样，不跳。
 */
export function decideUaSwitch(
  previous: UaClass | null,
  current: UaClass,
  hash: string,
): string | null {
  if (previous === null || previous === current) return null;
  const wasMobile = isMobileUaClass(previous);
  const nowMobile = isMobileUaClass(current);
  if (wasMobile === nowMobile) return null;
  const path = normalizeHashPath(hash);
  if (nowMobile) return isMobilePath(path) ? null : desktopToMobile(path);
  return isMobilePath(path) ? mobileToDesktop(path) : null;
}

export function readStoredUaClass(): UaClass | null {
  try {
    const stored = localStorage.getItem(UA_CLASS_STORAGE_KEY);
    return isUaClass(stored) ? stored : null;
  } catch {
    return null;
  }
}

function storeUaClass(value: UaClass): void {
  try {
    localStorage.setItem(UA_CLASS_STORAGE_KEY, value);
  } catch {
    /* 隐私模式 / 配额满：只影响下次比较，不影响当前页面 */
  }
}

/** 执行一次检查：总是记录当前类别，必要时改 hash。返回跳转目标（无则 null）。 */
export function applyUaSwitch(): string | null {
  if (typeof window === "undefined" || typeof navigator === "undefined") return null;
  const current = currentUaClass();
  const target = decideUaSwitch(readStoredUaClass(), current, window.location.hash);
  storeUaClass(current);
  if (!target) return null;
  try {
    window.history.replaceState(null, "", `#${target}`);
  } catch {
    // 极端环境（history 被限制）下的回退：会多一条历史记录但页面正确
    window.location.hash = target;
  }
  return target;
}
