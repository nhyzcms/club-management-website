/**
 * 模拟环境的生命周期：进入 / 退出 / 判定路由。
 *
 * 数据只活在**内存**里（同一份 `SimState` 被管理端与用户端两个 API 共用），所以
 * 「退出模拟」「刷新页面」「关掉标签页」三种结束方式都会自然清空，不需要清理逻辑。
 *
 * 安装必须发生在**页面渲染期间**（而不是 useEffect）：子组件的 useEffect 先跑，
 * 否则第一轮请求会打到正式环境。
 */
import { installPostcardAdminSimApi, type PostcardAdminApi } from "../api/postcardAdmin";
import { installPostcardSimApi, type PostcardApi } from "../api/postcard";
import { createSimPostcardAdminApi } from "./api";
import { createSimPostcardUserApi } from "./apiUser";
import { emptySimState, type SimState } from "./state";

export const SIM_BADGE_TEXT = "模拟环境";
export const SIM_QUERY = "sim";

/** 当前已安装的模拟实例（重渲染时复用它，避免把内存数据重建掉）。 */
let installed: { state: SimState; admin: PostcardAdminApi; user: PostcardApi } | null = null;

/** 当前路由是否模拟环境（`#/postcard?sim=1` 之类的任意页面）。 */
export function isSimRoute(hash: string = window.location.hash): boolean {
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return false;
  return new URLSearchParams(hash.slice(queryIndex + 1)).get(SIM_QUERY) === "1";
}

/** 给任意 hash 路由补上 `sim=1`（模拟环境内部跳转必须带着它）。 */
export function withSimParam(hash: string): string {
  if (hash.includes(`${SIM_QUERY}=1`)) return hash;
  return hash.includes("?") ? `${hash}&${SIM_QUERY}=1` : `${hash}?${SIM_QUERY}=1`;
}

/** 幂等安装：重复调用不会丢已有内存数据（StrictMode / 重渲染安全）。 */
export function enterSim(): void {
  if (installed) return;
  const state = emptySimState();
  const admin = createSimPostcardAdminApi(state);
  const user = createSimPostcardUserApi(state);
  installPostcardAdminSimApi(admin);
  installPostcardSimApi(user);
  installed = { state, admin, user };
}

/** 退出模拟：卸下两个实现并丢弃内存数据（含已上传的照片 data URL）。 */
export function exitSim(): void {
  if (!installed) return;
  installed = null;
  installPostcardAdminSimApi(null);
  installPostcardSimApi(null);
}

/** 是否处于模拟环境（下载文件名等处判断）。 */
export function isSimActive(): boolean {
  return installed !== null;
}
