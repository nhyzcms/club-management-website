import { useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import MobilePage from "../components/MobilePage";
import ConfigTab from "../components/postcard/admin/ConfigTab";
import BarcodeTab from "../components/postcard/admin/BarcodeTab";
import AITab from "../components/postcard/admin/AITab";
import ReviewTab from "../components/postcard/admin/ReviewTab";
import RecordsTab from "../components/postcard/admin/RecordsTab";
import StatsTab from "../components/postcard/admin/StatsTab";
import MiscTab from "../components/postcard/admin/MiscTab";
import { isMobileDevice } from "../utils/device";
import "../styles/postcard-admin.css";

const TABS = [
  { key: "config", label: "活动配置" },
  { key: "barcode", label: "条码" },
  { key: "ai", label: "AI 审核" },
  { key: "review", label: "复核台" },
  { key: "records", label: "登记记录" },
  { key: "stats", label: "统计" },
  { key: "misc", label: "建议与审计" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/**
 * 明信片互寄 · 管理端（`/#/postcard/admin`）。
 *
 * 一个页面七个 tab：配置 / 条码 / AI / 复核 / 记录 / 统计 / 建议与审计。
 * 权限真源在服务端（manage_postcard / review_postcard）：前端只做入口与
 * 403 提示，非管理员打开也拿不到任何数据。
 */
export default function PostcardAdminPage() {
  const isMobile = isMobileDevice();
  const [tab, setTab] = useState<TabKey>("config");

  useEffect(() => {
    document.title = "明信片管理 · 南汇一中传媒社";
  }, []);

  // 手机端横向 tab 条会溢出：选中的 tab 滚进可视区。
  useEffect(() => {
    const el = document.querySelector<HTMLElement>(`.pa-tab[data-active="true"]`);
    el?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [tab]);

  const content = (
    <div className="pa-page">
      <header className="pa-head">
        <div>
          <h1 className="pa-title">明信片互寄 · 管理端</h1>
          <p className="pa-sub">
            活动配置、条码、AI 审核与登记记录都在这里。
            <a className="pa-inline-link" href="#/postcard">
              返回用户页面
            </a>
            <a className="pa-inline-link" href="#/postcard/receive" target="_blank" rel="noopener noreferrer">
              签收扫码
            </a>
          </p>
        </div>
      </header>

      <nav className="pa-tabs" aria-label="管理端分区">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className="pa-tab"
            data-active={tab === t.key}
            aria-current={tab === t.key ? "page" : undefined}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="pa-body">
        {tab === "config" && <ConfigTab />}
        {tab === "barcode" && <BarcodeTab />}
        {tab === "ai" && <AITab />}
        {tab === "review" && <ReviewTab />}
        {tab === "records" && <RecordsTab />}
        {tab === "stats" && <StatsTab />}
        {tab === "misc" && <MiscTab />}
      </div>
    </div>
  );

  if (isMobile) {
    return (
      <MobilePage title="明信片管理" back="/postcard">
        {content}
      </MobilePage>
    );
  }
  return (
    <AppShell>
      <div className="page">
        <div className="container pa-container">{content}</div>
      </div>
    </AppShell>
  );
}
