/**
 * 模拟环境的生命周期：进入 / 退出 / 判定路由。
 *
 * 数据只活在**内存**里（`createSimPostcardAdminApi()` 的闭包），所以「退出模拟」
 * 「刷新页面」「关掉标签页」三种结束方式都会自然清空，不需要清理逻辑。
 *
 * 安装必须发生在**父组件渲染期间**（而不是 useEffect）：子 tab 的 useEffect 先跑，
 * 否则第一轮请求会打到正式环境。
 */
import { installPostcardAdminSimApi, type PostcardAdminApi } from "../api/postcardAdmin";
import { createSimPostcardAdminApi } from "./api";

export const SIM_BADGE_TEXT = "模拟环境";
export const SIM_QUERY = "sim";

/** 当前已安装的模拟实例（重渲染时复用它，避免把内存数据重建掉）。 */
let installed: PostcardAdminApi | null = null;

/** 当前路由是否模拟环境（`#/postcard/admin?sim=1`，PR2 的其他页面同参数）。 */
export function isSimRoute(hash: string = window.location.hash): boolean {
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return false;
  return new URLSearchParams(hash.slice(queryIndex + 1)).get(SIM_QUERY) === "1";
}

/** 幂等安装：重复调用不会丢已有内存数据（StrictMode / 重渲染安全）。 */
export function enterSim(): void {
  if (installed) return;
  installed = createSimPostcardAdminApi();
  installPostcardAdminSimApi(installed);
}

/** 退出模拟：卸下实现并丢弃内存数据。 */
export function exitSim(): void {
  installed = null;
  installPostcardAdminSimApi(null);
}

/** 是否处于模拟环境（供下载文件名等处判断）。 */
export function isSimActive(): boolean {
  return installed !== null;
}
