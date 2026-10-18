import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import MobileTabBar from "./MobileTabBar";
import "../styles/mobile.css";

interface Props {
  /** 顶栏标题。 */
  title: string;
  /** 返回目标：字符串走路由跳转，函数自行处理，缺省为浏览器后退。 */
  back?: string | (() => void);
  /** 顶栏右侧操作区（按钮 / 链接）。 */
  actions?: ReactNode;
  /** 是否挂底部 tab 栏（默认挂，与其余手机版页面一致）。 */
  tabBar?: boolean;
  /** 追加到 .m-app 的类名（如 m-review 用于页面级样式覆盖）。 */
  className?: string;
  children: ReactNode;
}

const chevron = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2.2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

/**
 * 手机版二级页框架：固定顶栏（返回 + 标题 + 右侧操作）+ 内容区 + 底部 tab。
 *
 * 为什么需要它：手机版首页/列表页各有自己的顶栏，但审核台、任务详情这类
 * 「从我的页进去的二级页」需要一个统一的返回语义（尤其 App 壳里没有浏览器
 * 工具栏，用户没有后退按钮可用）。
 */
export default function MobilePage({
  title,
  back,
  actions,
  tabBar = true,
  className,
  children,
}: Props) {
  const navigate = useNavigate();

  const goBack = () => {
    if (typeof back === "string") navigate(back);
    else if (typeof back === "function") back();
    else navigate(-1);
  };

  return (
    <div className={"m-app" + (className ? " " + className : "")}>
      <header className="m-topbar m-topbar-page">
        <button type="button" className="m-page-back" onClick={goBack} aria-label="返回">
          <svg viewBox="0 0 24 24" {...chevron} aria-hidden="true">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>
        <h1 className="m-page-title">{title}</h1>
        <div className="m-page-actions">{actions}</div>
      </header>
      <main className="m-page-body">{children}</main>
      {tabBar && <MobileTabBar />}
    </div>
  );
}
