import { useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import MobilePage from "../components/MobilePage";
import ConfirmModal from "../components/ConfirmModal";
import ConfigTab from "../components/postcard/admin/ConfigTab";
import BarcodeTab from "../components/postcard/admin/BarcodeTab";
import AITab from "../components/postcard/admin/AITab";
import RecordsTab from "../components/postcard/admin/RecordsTab";
import StatsTab from "../components/postcard/admin/StatsTab";
import MiscTab from "../components/postcard/admin/MiscTab";
import { isMobileDevice } from "../utils/device";
import { SIM_BADGE_TEXT, enterSim, exitSim, isSimRoute } from "../postcardSim/session";
import "../styles/postcard-admin.css";

const TABS = [
  { key: "config", label: "活动配置" },
  { key: "barcode", label: "条码" },
  { key: "ai", label: "AI 审核" },
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
 *
 * 模拟环境（`?sim=1`，用户 2026-11-08 要求）：同一套界面，数据换成内存沙箱，
 * 供管理员教学演练与验收新功能；退出 / 刷新即清空，不碰正式数据。
 */
export default function PostcardAdminPage() {
  const isMobile = isMobileDevice();
  const [tab, setTab] = useState<TabKey>("config");
  const [askingSim, setAskingSim] = useState(false);
  // 自己订阅 hashchange：本页不依赖 router 的 location（Route 在只变 search 时不一定
  // 重渲染，而模拟环境的开关正好只改 search）。
  const [sim, setSim] = useState(() => isSimRoute());

  useEffect(() => {
    const sync = () => setSim(isSimRoute());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  // 必须在渲染期装载：子 tab 的 useEffect 先于本组件的 effect 跑，晚一步就会
  // 让第一轮请求打到正式环境。enterSim 幂等，重渲染不会丢内存数据。
  if (sim) enterSim();

  useEffect(() => {
    document.title = sim ? "明信片管理（模拟环境） · 南汇一中传媒社" : "明信片管理 · 南汇一中传媒社";
  }, [sim]);

  // 退出模拟 / 离开本页 → 卸下沙箱，内存数据随之丢弃。
  useEffect(() => {
    if (!sim) return undefined;
    return () => exitSim();
  }, [sim]);

  // 手机端横向 tab 条会溢出：选中的 tab 滚进可视区。
  useEffect(() => {
    const el = document.querySelector<HTMLElement>(`.pa-tab[data-active="true"]`);
    el?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [tab]);

  const goSim = () => {
    setAskingSim(false);
    window.location.hash = "#/postcard/admin?sim=1";
  };

  const leaveSim = () => {
    window.location.hash = "#/postcard/admin";
  };

  const content = (
    <div className={sim ? "pa-page pa-page-sim" : "pa-page"}>
      <header className="pa-head">
        <div>
          <h1 className="pa-title">
            明信片互寄 · 管理端
            {sim && <span className="pa-sim-badge">{SIM_BADGE_TEXT}</span>}
          </h1>
          <p className="pa-sub">
            {sim ? (
              <>
                模拟环境：这里的填写与操作全部只存在于本标签页内存，退出或刷新即清空，不会写入正式数据。
                <button type="button" className="pa-inline-link pa-inline-btn" onClick={leaveSim}>
                  退出模拟
                </button>
              </>
            ) : (
              <>
                活动配置、条码、AI 审核与登记记录都在这里。
                <a className="pa-inline-link" href="#/postcard">
                  返回用户页面
                </a>
                <a
                  className="pa-inline-link"
                  href="#/postcard/receive"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  签收扫码
                </a>
                {/* 复核并入全站审核台：这里只留入口，不再单开一桌（2026-11-08 用户要求）。 */}
                <a className="pa-inline-link" href="#/reviews?kind=postcard">
                  去审核台复核
                </a>
                {/* 模拟环境入口（紧跟在复核入口之后，2026-11-08 用户要求）。 */}
                <button
                  type="button"
                  className="pa-inline-link pa-inline-btn"
                  onClick={() => setAskingSim(true)}
                >
                  模拟活动
                </button>
              </>
            )}
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

      {/* key 跟着 sim 变：切换环境时让各 tab 重新挂载、重新取数。 */}
      <div className="pa-body" key={sim ? "sim" : "real"}>
        {tab === "config" && <ConfigTab />}
        {tab === "barcode" && <BarcodeTab />}
        {tab === "ai" && <AITab />}
        {tab === "records" && <RecordsTab />}
        {tab === "stats" && <StatsTab />}
        {tab === "misc" && <MiscTab />}
      </div>
    </div>
  );

  const shell = isMobile ? (
    <MobilePage title={sim ? "明信片管理 · 模拟" : "明信片管理"} back="/postcard">
      {content}
    </MobilePage>
  ) : (
    <AppShell>
      <div className="page">
        <div className="container pa-container">{content}</div>
      </div>
    </AppShell>
  );

  return (
    <>
      {shell}
      {askingSim && (
        <ConfirmModal
          title="是否进入模拟操作"
          confirmLabel="进入模拟"
          onCancel={() => setAskingSim(false)}
          onConfirm={goSim}
        >
          <p>模拟环境与正式版界面一致，但所有数据只存在本标签页内存：</p>
          <p style={{ marginTop: 8 }}>
            仅供管理员教学演练与验收新功能，退出或刷新即清空，<b>不会写入也不会改动正式数据</b>。
          </p>
        </ConfirmModal>
      )}
    </>
  );
}
