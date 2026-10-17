/** 手机设备判定（按 UA）：手机访问站点首页时直接进入手机版（/#/m）。
 *
 * 命中 iPhone / Android / Windows Phone 等常见手机 UA；桌面浏览器以及手机浏览器
 * 「请求桌面站点」模式（UA 不再含手机特征）不会命中。
 */
export function isMobileDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iPhone|iPod|Android|Windows Phone|BlackBerry|Opera Mini|IEMobile|Mobile/i.test(
    navigator.userAgent,
  );
}

/** 是否运行在自家 Android 壳里（UA 标记由壳注入，见 app 仓库 AppConfig.uaMarker）。
 *
 * 用途：让 App 专属行为只在壳里生效 —— 例如「首次启动默认跟随系统深色」
 * （见 theme.ts 的 getTheme）。浏览器（含手机浏览器）不受影响。
 * 标记格式固定为 `NhyzClubApp/<versionName> (Android; <versionCode>)`。
 */
export function isAppShell(): boolean {
  if (typeof navigator === "undefined") return false;
  return /NhyzClubApp\//.test(navigator.userAgent);
}
