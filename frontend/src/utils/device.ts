/** UA 三档分类：自家 App 壳 / 手机浏览器 / 桌面浏览器。
 *
 * 页面分流只关心「移动侧 / 桌面侧」（见 utils/uaSwitch.ts），但把壳单独列出来，
 * 便于 theme.ts 等只在壳内生效的逻辑继续复用同一处判定。
 */
export type UaClass = "app" | "mobile" | "desktop";

const MOBILE_UA_RE = /iPhone|iPod|Android|Windows Phone|BlackBerry|Opera Mini|IEMobile|Mobile/i;
const APP_SHELL_UA_RE = /NhyzClubApp\//;

/** 纯函数：按 UA 字符串分类（不读全局，方便单测）。
 *
 * 先判壳：壳的 UA 是「手机 UA + 追加标记」，若先判手机就永远分不出 app 与 mobile。
 */
export function classifyUserAgent(ua: string): UaClass {
  const text = ua || "";
  if (APP_SHELL_UA_RE.test(text)) return "app";
  if (MOBILE_UA_RE.test(text)) return "mobile";
  return "desktop";
}

/** 当前 UA 的分类（浏览器环境外一律视为桌面）。 */
export function currentUaClass(): UaClass {
  if (typeof navigator === "undefined") return "desktop";
  return classifyUserAgent(navigator.userAgent);
}

/** 是否属于「移动侧」（手机浏览器或 App 壳，两者共用 /#/m 那套页面）。 */
export function isMobileUaClass(cls: UaClass): boolean {
  return cls !== "desktop";
}

export function isUaClass(value: string | null | undefined): value is UaClass {
  return value === "app" || value === "mobile" || value === "desktop";
}

/** 手机设备判定（按 UA）：手机访问站点首页时直接进入手机版（/#/m）。
 *
 * 命中 iPhone / Android / Windows Phone 等常见手机 UA；桌面浏览器以及手机浏览器
 * 「请求桌面站点」模式（UA 不再含手机特征）不会命中。
 */
export function isMobileDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  return isMobileUaClass(currentUaClass());
}

/** 是否运行在自家 Android 壳里（UA 标记由壳注入，见 app 仓库 AppConfig.uaMarker）。
 *
 * 用途：让 App 专属行为只在壳里生效 —— 例如「首次启动默认跟随系统深色」
 * （见 theme.ts 的 getTheme）。浏览器（含手机浏览器）不受影响。
 * 标记格式固定为 `NhyzClubApp/<versionName> (Android; <versionCode>)`。
 */
export function isAppShell(): boolean {
  if (typeof navigator === "undefined") return false;
  return currentUaClass() === "app";
}
