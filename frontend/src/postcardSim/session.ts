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

/**
 * 退出模拟并回到正式环境。
 *
 * 必须 **reload**：只卸载沙箱的话，已经渲染出来的页面还留着模拟数据（用户页
 * 不会重新取数），看起来像是「退出了但数据还在」。刷新是最省事也最不会出错的
 * 做法——沙箱本来就在内存里，刷新即清空，与需求一致。
 */
export function exitSimAndReload(hash = "#/postcard/admin"): void {
  exitSim();
  if (window.location.hash !== hash) window.location.hash = hash;
  window.location.reload();
}

/** 沙箱是否已装载（与 URL 无关：进了模拟就一直有效，直到退出 / 刷新）。 */
export function isSimActive(): boolean {
  return installed !== null;
}

/**
 * 当前是否处于「模拟模式」：URL 带 sim=1，或沙箱已经装着。
 *
 * 为什么要算后者：模拟里在用户页 ↔ 管理端之间来回切时不想丢数据，所以离开
 * 带参 URL 后沙箱继续留着；这时界面仍然得显示「模拟环境」，否则用户会以为
 * 自己在正式环境里操作。
 */
export function isSimMode(): boolean {
  return isSimActive() || isSimRoute();
}

/** 明信片这条业务链上的页面：切换这些页面不清空沙箱。 */
const SIM_SURFACES = [/^#\/postcard(\/|$)/, /^#\/reviews(\/|$)/, /^#\/m\/review(\/|$)/];

export function isPostcardSurface(hash: string = window.location.hash): boolean {
  const path = hash.split("?")[0];
  return SIM_SURFACES.some((re) => re.test(path));
}
