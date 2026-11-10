/**
 * Marzipano 渲染器懒加载（自托管，绝不发第三方请求）。
 *
 * 渲染器文件来自仓库既有静态资源 `/static/panorama/marzipano.js`：它与旧静态全景页
 * 共用同一份文件，且已被 scripts/pack-release.sh 与 scripts/check_panorama_static.py
 * 纳入发布完整性校验，所以在线上必然存在。
 *
 * ❗ 退役 `static/panorama/` 之前，必须先把 `marzipano.js` 迁到新位置并同步
 *    `PANORAMA_RENDERER_URL`（否则全景浏览页会加载失败）。
 *
 * 不把它做成 npm 依赖的原因：Marzipano 是与 npm 构建链无关的独立 UMD 产物，
 * 引入依赖需同步重算 package-lock.json，而本页只需要它的两个构造函数。
 */
import { PANORAMA_RENDERER_URL } from "../constants";

declare global {
  interface Window {
    Marzipano?: any;
  }
}

let pending: Promise<any> | null = null;

/** 确保 Marzipano 已就绪（幂等，允许失败后重试）。 */
export function loadMarzipano(): Promise<any> {
  if (window.Marzipano) return Promise.resolve(window.Marzipano);
  if (pending) return pending;

  pending = new Promise<any>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PANORAMA_RENDERER_URL;
    script.async = true;
    script.onload = () => {
      if (window.Marzipano) resolve(window.Marzipano);
      else reject(new Error("全景渲染器未就绪（Marzipano 未挂载到 window）"));
    };
    script.onerror = () => {
      pending = null; // 允许后续重试
      reject(new Error("全景渲染器加载失败"));
    };
    document.head.appendChild(script);
  });

  return pending;
}

/** 预载一张图（首屏先出低清预览，细节瓦片交给 Marzipano 渐进补齐）。 */
export function preloadImage(url: string): Promise<void> {
  return new Promise<void>((resolve) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = () => resolve(); // 预载失败不阻塞主流程
    img.src = url;
  });
}
