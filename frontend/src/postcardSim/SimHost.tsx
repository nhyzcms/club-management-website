import { useEffect, useState } from "react";
import {
  SIM_BADGE_TEXT,
  enterSim,
  exitSim,
  exitSimAndReload,
  isPostcardSurface,
  isSimMode,
  isSimRoute,
  withSimParam,
} from "./session";
import "../styles/postcard-sim.css";

/**
 * 模拟环境的全局宿主（挂在 `<HashRouter>` 里、`<Routes>` 外面）。
 *
 * 生命周期（2026-11-09 用户要求）：
 * - 进入：URL 带 `?sim=1` 即装载内存沙箱；
 * - **保持**：在明信片这条链上（用户端 / 管理端 / 签收 / 审核台）来回切换不卸载，
 *   所以「普通用户页面 ↔ 管理员页面」怎么跳都不会丢测试数据；
 * - 退出：点「退出模拟」，或离开这条链（回到主页 / 新闻等）——关标签页与刷新
 *   本来就会随内存消失。
 *
 * 另外给「没有自己标题栏位置」的模拟页提供一个固定的红底白字标识 + 退出按钮
 * （管理端自己有内联徽标，不重复显示）。
 */
export default function PostcardSimHost() {
  const [sim, setSim] = useState(() => isSimMode());
  const [onAdmin, setOnAdmin] = useState(
    () => window.location.hash.split("?")[0] === "#/postcard/admin",
  );

  useEffect(() => {
    const sync = () => {
      const hash = window.location.hash;
      if (isSimRoute(hash)) enterSim();
      else if (!isPostcardSurface(hash)) exitSim();
      setSim(isSimMode());
      setOnAdmin(hash.split("?")[0] === "#/postcard/admin");
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  // 兜底：初次进入带参页面时补装一次（页面自己也会在渲染期装，幂等）。
  useEffect(() => {
    if (isSimRoute()) enterSim();
  }, []);

  if (!sim || onAdmin) return null;

  return (
    <div className="pc-sim-dock" role="status">
      <span className="pc-sim-dock-badge">{SIM_BADGE_TEXT}</span>
      <span className="pc-sim-dock-text">数据只在本标签页内存里，退出即清空</span>
      <button
        type="button"
        className="pc-sim-dock-exit"
        onClick={() => {
          window.location.hash = withSimParam("#/postcard/admin");
        }}
      >
        管理端
      </button>
      <button
        type="button"
        className="pc-sim-dock-exit"
        onClick={() => exitSimAndReload("#/postcard")}
      >
        退出模拟
      </button>
    </div>
  );
}
