/** App「关于」页的静态信息（名称 / 许可 / 链接）与版本号解析。
 *
 * 为什么单独抽一个模块：这些字面量既是页面内容，也是单测的断言对象；
 * 版本号**不写死**在源码里 —— 壳把 `NhyzClubApp/<versionName> (Android; <versionCode>)`
 * 注进 UA（见 app 仓库 `shell/AppConfig.uaMarker()`），网页这边解析即可，
 * 网站发布不必跟着 APK 的 version.properties 一起改（改漏就会显示过期版本号）。
 *
 * 页面只在自家壳里可见（`isAppShell()`），手机浏览器永远看不到这一页。
 */
import { parseShellVersion } from "./shellVersion";

/** App 显示名（与壳的 `res/values/strings.xml` 的 `app_name` 一致）。 */
export const APP_NAME = "南汇一中传媒社";

/** 图标资源：`frontend/public/app-icon.svg` 会被 webpack 拷进 dist 根目录，
 * 由 Django staticfiles 挂在 `/static/` 下（与 `/static/favicon.ico` 同一套，见 template.html）。
 */
export const APP_ICON = "/static/app-icon.svg";

/** 官网。 */
export const APP_WEBSITE = "https://nhyzcms.github.io";

/** 开源地址（壳仓库）。 */
export const APP_SOURCE = "https://github.com/nhyzcms/app";

/** 开源协议（两仓 LICENSE 均为 BSD 3-Clause，2026-10-17 起网站侧由 MIT 换为它）。 */
export const APP_LICENSE = "BSD 3-Clause License";

/** 著作权人。 */
export const APP_COPYRIGHT = "南汇一中传媒社信息组";

/** 著作权年份（LICENSE 首行 `Copyright (c) 2026`）。 */
export const APP_COPYRIGHT_YEAR = "2026";

/** 纯函数：把 UA 里的壳版本拼成给人看的一行；非壳 UA 返回 null。
 *
 * 例：壳 UA → `0.2.0（版本码 2）`；chromobile 浏览器 → null。
 * 解析出版本名但拿不到版本码时只显示 versionName，不编数字。
 */
export function appVersionLabel(ua: string): string | null {
  const info = parseShellVersion(ua);
  if (!info) return null;
  return info.versionCode === null ? info.versionName : `${info.versionName}（版本码 ${info.versionCode}）`;
}
