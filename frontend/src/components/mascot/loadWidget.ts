/**
 * 看板娘 overlay adapter. Lives in the "mascot-widget" chunk only.
 *
 * live2d-widget supplies chrome (tips, tools). Cubism 2's `loadlive2d` cannot
 * parse `.model3.json`, and pixi-live2d-display 0.4's Cubism 4 framework does
 * not draw against Cubism 5/6 Core. Rendering goes through `l2d` (official
 * Cubism 2 & 6 SDK wrapper) so `.model.json` and `.model3.json` share one API.
 *
 * Catalog: `/static/live2d/catalog.json`. Widget cubism*Path is omitted so
 * live2d-widget does not also attach a WebGL context to #live2d.
 */

import { init, type L2D } from "l2d";

const LIVE2D_BASE = "/static/live2d/";
const WIDGET_BASE = `${LIVE2D_BASE}widget/`;
const CATALOG_URL = `${LIVE2D_BASE}catalog.json`;
const WAIFU_DISPLAY_KEY = "waifu-display";
const WAIFU_DISABLED_KEY = "waifu-disabled";
const MODEL_ID_KEY = "modelId";
const SENTINEL_ATTR = "data-mascot-sentinel";

type CatalogModel = { id: string; name: string; entry: string };
type Catalog = { version: number; models: CatalogModel[] };

declare global {
  interface Window {
    initWidget?: (config: {
      waifuPath: string;
      tools?: string[];
      logLevel?: string;
    }) => void;
  }
}

export type MountMascotWidgetOptions = {
  onClose: () => void;
};

export type MascotWidgetHandle = {
  unmount: () => void;
};

let scriptsPromise: Promise<void> | null = null;

function loadCss(href: string): Promise<void> {
  if (document.querySelector(`link[href="${href}"]`)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.onload = () => resolve();
    link.onerror = () => reject(new Error(`Failed to load ${href}`));
    document.head.appendChild(link);
  });
}

function loadScript(src: string, module = false): Promise<void> {
  if (document.querySelector(`script[src="${src}"]`)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    if (module) script.type = "module";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

function ensureScripts(): Promise<void> {
  if (!scriptsPromise) {
    scriptsPromise = Promise.all([
      loadCss(`${WIDGET_BASE}waifu.css`),
      loadScript(`${WIDGET_BASE}waifu-tips.js`, true),
    ]).then(() => undefined);
  }
  return scriptsPromise;
}

function modelUrl(entry: string): string {
  return `${LIVE2D_BASE}${entry.split("/").map(encodeURIComponent).join("/")}`;
}

function waitForId(id: string, timeoutMs = 5000): Promise<HTMLElement> {
  return new Promise((resolve, reject) => {
    const hit = document.getElementById(id);
    if (hit) {
      resolve(hit);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      const el = document.getElementById(id);
      if (el) {
        window.clearInterval(timer);
        resolve(el);
        return;
      }
      if (Date.now() - started > timeoutMs) {
        window.clearInterval(timer);
        reject(new Error(`#${id} not found`));
      }
    }, 40);
  });
}

function pinLive2dId(engine: L2D): void {
  const canvas = engine.getCanvas();
  const existing = document.getElementById("live2d");
  if (existing && existing !== canvas) existing.removeAttribute("id");
  canvas.id = "live2d";
}

/**
 * Cubism 2 and Cubism 6 cannot share a WebGL context. `l2d.load()` clones the
 * canvas only when one L2D instance switches versions. destroy()+init() zeros
 * `currentVersion`, so that clone never runs — leftover GL state draws the next
 * model's atlas as exploded mesh fragments. Always start from a virgin canvas.
 */
function replaceLive2dCanvas(old: HTMLCanvasElement): HTMLCanvasElement {
  const next = document.createElement("canvas");
  next.id = "live2d";
  next.className = old.className;
  next.style.cssText = old.style.cssText;
  const size = Math.max(300, Math.round(old.clientWidth) || 300);
  next.width = size;
  next.height = size;
  next.style.width = `${size}px`;
  next.style.height = `${size}px`;
  old.parentNode?.replaceChild(next, old);
  return next;
}

function removeStockNodes(): void {
  document.getElementById("waifu")?.remove();
  document.getElementById("waifu-toggle")?.remove();
  document.querySelector(`[${SENTINEL_ATTR}]`)?.remove();
}

/** Keep #waifu-tips so leftover stock intervals/listeners do not throw after unmount. */
function placeTipsSentinel(): void {
  if (document.getElementById("waifu-tips")) return;
  const sentinel = document.createElement("div");
  sentinel.id = "waifu-tips";
  sentinel.hidden = true;
  sentinel.setAttribute(SENTINEL_ATTR, "1");
  document.body.appendChild(sentinel);
}

function readModelIndex(length: number): number {
  const raw = parseInt(localStorage.getItem(MODEL_ID_KEY) ?? "0", 10);
  if (Number.isNaN(raw) || raw < 0 || raw >= length) return 0;
  return raw;
}

export async function mountMascotWidget(
  options: MountMascotWidgetOptions,
): Promise<MascotWidgetHandle> {
  await ensureScripts();

  const catalog: Catalog = await fetch(CATALOG_URL).then((res) => {
    if (!res.ok) throw new Error(`catalog.json ${res.status}`);
    return res.json();
  });
  const models = catalog.models;
  if (!models?.length) {
    throw new Error("catalog.json has no models");
  }

  if (typeof window.initWidget !== "function") {
    throw new Error("Live2D widget globals missing after script injection");
  }

  removeStockNodes();
  localStorage.removeItem(WAIFU_DISPLAY_KEY);
  localStorage.removeItem(WAIFU_DISABLED_KEY);

  window.initWidget({
    waifuPath: `${WIDGET_BASE}waifu-tips.json`,
    tools: ["hitokoto", "switch-model", "photo", "info", "quit"],
    logLevel: "error",
  });

  document.getElementById("waifu-toggle")?.setAttribute("hidden", "");

  let engine: L2D | null = null;
  let index = readModelIndex(models.length);
  let loading = false;

  const loadAt = async (nextIndex: number): Promise<void> => {
    if (loading) return;
    loading = true;
    try {
      engine?.destroy();
      engine = null;
      const stale = (await waitForId("live2d")) as HTMLCanvasElement;
      const canvas = replaceLive2dCanvas(stale);
      const next = init(canvas);
      if (!next) throw new Error("l2d init failed");
      engine = next;
      await engine.load({
        path: modelUrl(models[nextIndex].entry),
        volume: 0,
        logLevel: "error",
      });
      pinLive2dId(engine);
      index = nextIndex;
      localStorage.setItem(MODEL_ID_KEY, String(index));
    } finally {
      loading = false;
    }
  };

  await loadAt(index);

  const onToolClick = (event: Event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("#waifu-tool-switch-model")) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      void loadAt((index + 1) % models.length);
      return;
    }
    if (target.closest("#waifu-tool-quit")) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      localStorage.removeItem(WAIFU_DISPLAY_KEY);
      localStorage.removeItem(WAIFU_DISABLED_KEY);
      options.onClose();
    }
  };
  document.addEventListener("click", onToolClick, true);

  let unmounted = false;
  return {
    unmount: () => {
      if (unmounted) return;
      unmounted = true;
      document.removeEventListener("click", onToolClick, true);
      engine?.destroy();
      engine = null;
      removeStockNodes();
      placeTipsSentinel();
      localStorage.removeItem(WAIFU_DISPLAY_KEY);
    },
  };
}
