import { useEffect } from "react";
import MobilePage from "../components/MobilePage";
import {
  APP_COPYRIGHT,
  APP_COPYRIGHT_YEAR,
  APP_ICON,
  APP_LICENSE,
  APP_NAME,
  APP_SOURCE,
  APP_WEBSITE,
  appVersionLabel,
} from "../utils/aboutApp";
import "../styles/mobile-about.css";

/**
 * 「关于 APP」页（`/#/m/about-app`）。
 *
 * 只在自家 Android 壳里可达：入口由 `MobileMePage` 按 `isAppShell()` 决定是否出现，
 * 路由本身在 `App.tsx` 里也做了门禁（浏览器直接手输地址会跳回「我的」）。
 * 因此这一页**不需要**任何接口 —— 图标、名称、协议、官网都是常量，版本号来自壳注入的 UA。
 *
 * 链接一律用普通 `<a href>`：壳的导航策略（app 仓库 `shell/NavPolicy`）会把非站内主机
 * 交给系统浏览器打开；`target="_blank"` 在 WebView 里可能被吞掉（没有多窗口支持），
 * 所以刻意不写。
 */
export default function MobileAboutAppPage() {
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  const version = appVersionLabel(ua);

  useEffect(() => {
    document.title = `关于 APP · ${APP_NAME}`;
  }, []);

  return (
    <MobilePage title="关于 APP" back="/m/me">
      <section className="m-about-hero">
        <img className="m-about-icon" src={APP_ICON} alt={`${APP_NAME} App 图标`} width={88} height={88} />
        <div className="m-about-name">{APP_NAME}</div>
        <div className="m-about-ver">版本 {version ?? "未知"}</div>
        <div className="m-about-sub">上海市南汇第一中学传媒社 · 官方 App</div>
      </section>

      <div className="m-list m-about-list">
        <div className="m-about-row">
          <span className="m-about-key">开源协议</span>
          <span className="m-about-val">{APP_LICENSE}</span>
        </div>
        <div className="m-about-row">
          <span className="m-about-key">著作权人</span>
          <span className="m-about-val">
            © {APP_COPYRIGHT_YEAR} {APP_COPYRIGHT}
          </span>
        </div>
        <div className="m-about-row">
          <span className="m-about-key">官网</span>
          <a className="m-about-link" href={APP_WEBSITE} rel="noopener noreferrer">
            nhyzcms.github.io
          </a>
        </div>
        <div className="m-about-row">
          <span className="m-about-key">开源地址</span>
          <a className="m-about-link" href={APP_SOURCE} rel="noopener noreferrer">
            github.com/nhyzcms/app
          </a>
        </div>
      </div>

      <p className="m-about-foot">
        App 由原生壳（Kotlin + 系统 WebView）与本站网页共同组成，网页部分随网站同步更新，
        无需重新安装。壳的源码按 {APP_LICENSE} 开源，可在
        <a className="m-about-link" href={APP_SOURCE} rel="noopener noreferrer">
          开源地址
        </a>
        查看。
      </p>
    </MobilePage>
  );
}
