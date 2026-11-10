/**
 * 全局常量（前端单一来源）。
 *
 * 校园全景图入口：
 * - 浏览页已是站内 SPA 页 `/#/panorama`（服务端切片 + 多级瓦片，见 ADR-0022），
 *   「关于 → 校园一览」下方固定按钮指向它；
 * - 旧的静态页 `/static/panorama/index.html` 仍在仓库与发布包里（可直接访问，作为兜底），
 *   但已不再挂入口；退役前必须先把 `marzipano.js` 迁到新位置并同步 PANORAMA_RENDERER_URL，
 *   同时更新 scripts/pack-release.sh 与 scripts/check_panorama_static.py。
 */
export const PANORAMA_PAGE_URL = "/#/panorama";

/**
 * Marzipano 渲染器（自托管静态资源，勿改成 CDN）。
 *
 * 与旧静态全景页共用同一份文件，且被 scripts/pack-release.sh 与
 * scripts/check_panorama_static.py 纳入发布完整性校验。
 */
export const PANORAMA_RENDERER_URL = "/static/panorama/marzipano.js";
