/** App 壳版本闸门（区块 8）：从壳注入的 UA 标记里解析 versionCode，判断网站是否还支持这个壳。
 *
 * UA 契约（见 app 仓库 `shell/AppConfig.uaMarker()`）：
 *   `NhyzClubApp/<versionName> (Android; <versionCode>)`
 * 例：`... Mobile Safari/537.36 NhyzClubApp/0.2.0 (Android; 2) NhyzClubShell/0.2.0 (native; 2)`
 *
 * 为什么用 versionCode 而不是 versionName：versionCode 是单调递增的整数（Android 不允许降级安装），
 * 直接比大小即可；versionName 是给人看的三段式，比较时要处理 `0.10.0` vs `0.9.0` 这类坑。
 */
import { classifyUserAgent } from "./device";

/** 网站要求的最低壳版本码。
 *
 * 当前 = 2（v0.2.0）：该版本起壳才具备网站依赖的原生能力 ——
 * 网页内 `getUserMedia` 相机授权（`onPermissionRequest`）与安全补丁对齐。
 * 提高这个值等于"把老壳用户挡在门外"，只有在老壳真的会让网站出错时才动它。
 */
export const MIN_SHELL_VERSION_CODE = 2;

export interface ShellVersionInfo {
  versionName: string;
  /** UA 里没带版本码（理论上不会）时为 null —— 此时一律放行，不拿用户做实验。 */
  versionCode: number | null;
}

const APP_VERSION_RE = /NhyzClubApp\/([0-9A-Za-z._-]+)(?:\s*\(Android;\s*(\d+)\s*\))?/;

/** 纯函数：解析 UA 里的壳版本；非壳 UA 返回 null。 */
export function parseShellVersion(ua: string): ShellVersionInfo | null {
  const m = APP_VERSION_RE.exec(ua || "");
  if (!m) return null;
  const code = m[2] ? Number.parseInt(m[2], 10) : Number.NaN;
  return {
    versionName: m[1],
    versionCode: Number.isFinite(code) ? code : null,
  };
}

export type ShellVersionState = "ok" | "outdated" | "unknown";

/** 纯函数：门禁判定。
 *
 * - 浏览器（含手机浏览器）→ `ok`，闸门只管自家壳；
 * - 壳版本码 < 最低要求 → `outdated`；
 * - 壳 UA 解析不出版本码 → `unknown`（调用方按"放行"处理）。
 */
export function evaluateShellVersion(
  ua: string,
  minVersionCode: number = MIN_SHELL_VERSION_CODE,
): ShellVersionState {
  if (classifyUserAgent(ua) !== "app") return "ok";
  const info = parseShellVersion(ua);
  if (!info || info.versionCode === null) return "unknown";
  return info.versionCode < minVersionCode ? "outdated" : "ok";
}
