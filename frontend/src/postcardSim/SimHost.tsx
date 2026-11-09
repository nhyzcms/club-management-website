import { useEffect, useState } from "react";
import { SIM_BADGE_TEXT, enterSim, exitSim, isSimRoute } from "./session";
import "../styles/postcard-sim.css";

/**
 * 模拟环境的全局宿主（挂在 `<HashRouter>` 里、`<Routes>` 外面）。
 *
 * 职责只有两件：
 * 1. 跟着 URL 走：离开带 `?sim=1` 的页面就卸下沙箱（内存数据随之丢弃）；
 * 2. 给「没有自己标题栏位置」的模拟页（用户端登记页 / 审核台 / 签收页）
 *    提供一个固定的红底白字标识 + 退出按钮——管理端自己有内联徽标，不重复显示。
 */
export default function PostcardSimHost() {
  const [sim, setSim] = useState(() => isSimRoute());
  const [onAdmin, setOnAdmin] = useState(() => window.location.hash.split("?")[0] === "#/postcard/admin");

  useEffect(() => {
    const sync = () => {
      setSim(isSimRoute());
      setOnAdmin(window.location.hash.split("?")[0] === "#/postcard/admin");
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  // 页面自己会在渲染期 enterSim()；这里只负责「离开模拟就卸掉」。
  useEffect(() => {
    if (!sim) exitSim();
    return undefined;
  }, [sim]);

  // 兜底：万一某个 sim 页忘了在渲染期安装（新增页面时），这里补一次。
  useEffect(() => {
    if (sim) enterSim();
  }, [sim]);

  if (!sim || onAdmin) return null;

  return (
    <div className="pc-sim-dock" role="status">
      <span className="pc-sim-dock-badge">{SIM_BADGE_TEXT}</span>
      <span className="pc-sim-dock-text">数据只在本标签页内存里，退出即清空</span>
      <button
        type="button"
        className="pc-sim-dock-exit"
        onClick={() => {
          window.location.hash = "#/postcard/admin";
        }}
      >
        退出模拟
      </button>
    </div>
  );
}
