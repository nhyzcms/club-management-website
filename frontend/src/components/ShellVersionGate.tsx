import { useState } from "react";
import {
  MIN_SHELL_VERSION_CODE,
  evaluateShellVersion,
  parseShellVersion,
} from "../utils/shellVersion";
import "./ShellVersionGate.css";

/** 最新版 APK 的自托管地址（nginx `location /app-update/`，见 app 仓库 docs/APP-MANIFEST.md）。
 * 用相对路径，换域名/端口都不用改这里。
 */
const APK_URL = "/app-update/latest.apk";

/**
 * App 壳最低版本闸门（区块 8）。
 *
 * 只在自家壳内、且 UA 里的 versionCode 低于 [MIN_SHELL_VERSION_CODE] 时出现：
 * 壳太老会缺网站依赖的原生能力（例如网页内的相机授权），表现为"点了没反应"，
 * 用户根本猜不到是版本问题 —— 所以直接把话说清楚，并给一条能立刻走的路。
 *
 * 两条设计红线：
 * 1. **可以不看**：底部"暂时继续"关掉本次会话（不写 localStorage），
 *    避免闸门自身误判把用户锁死在门外；
 * 2. **不猜**：解析不出版本码就不拦（`unknown`），宁可少提示一次。
 */
export default function ShellVersionGate() {
  const [dismissed, setDismissed] = useState(false);

  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  if (dismissed || evaluateShellVersion(ua) !== "outdated") return null;
  const current = parseShellVersion(ua);

  return (
    <div className="shell-gate" role="alertdialog" aria-modal="true" aria-labelledby="shell-gate-title">
      <div className="shell-gate-card">
        <div className="shell-gate-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
            strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3v12" />
            <path d="m7 10 5 5 5-5" />
            <path d="M4 20h16" />
          </svg>
        </div>
        <h1 id="shell-gate-title">请更新 App</h1>
        <p className="shell-gate-body">
          {`当前 App 版本 ${current?.versionName ?? "未知"}（版本码 ${current?.versionCode ?? "?"}），`
            + `网站已要求版本码 ${MIN_SHELL_VERSION_CODE} 及以上。`
            + "旧版本缺少相机授权等能力，部分功能点了会没有反应。"}
        </p>
        <a className="shell-gate-primary" href={APK_URL} download>
          下载最新版 APK
        </a>
        <p className="shell-gate-hint">
          下载完成后点通知栏里的安装包即可覆盖安装；同一签名，登录状态与本地设置都会保留。
          也可以先关掉 App 再打开，壳会在启动时自动提示更新。
        </p>
        <button type="button" className="shell-gate-secondary" onClick={() => setDismissed(true)}>
          暂时继续（部分功能可能不可用）
        </button>
      </div>
    </div>
  );
}
