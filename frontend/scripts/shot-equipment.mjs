// 临时脚本：为 PR 截图（功能示意图），跑完即删。
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { chromium } from "playwright";

const DIST = new URL("../dist/", import.meta.url).pathname;
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".ttf": "font/ttf",
  ".ico": "image/x-icon",
};

const me = {
  user: { id: 1, username: "zhangsan", email: "", permissions: {} },
  must_change_password: false,
  role: { label: "社员", variant: "user" },
  profile: { avatar: null, nickname: "张三", birthday: null, gender: "", bio: "", is_verified: true },
};
const profile = {
  user: { id: 1, username: "zhangsan", date_joined: "2025-09-01T08:00:00+08:00" },
  profile: { avatar: null, nickname: "张三", bio: "" },
  role: { label: "社员", variant: "user" },
  viewer: { is_owner: true, is_admin: false, is_member: true },
};
const items = [
  { id: 5, name: "佳能 EOS R6 相机", created_at: "2026-11-10T10:00:00+08:00", updated_at: "2026-11-10T10:00:00+08:00" },
  { id: 4, name: "EF 24-105mm f/4 镜头", created_at: "2026-11-10T10:01:00+08:00", updated_at: "2026-11-10T10:01:00+08:00" },
  { id: 3, name: "曼富图三脚架", created_at: "2026-11-10T10:02:00+08:00", updated_at: "2026-11-10T10:02:00+08:00" },
  { id: 2, name: "MacBook Pro 14（可剪 4K）", created_at: "2026-11-10T10:03:00+08:00", updated_at: "2026-11-10T10:03:00+08:00" },
  { id: 1, name: "SanDisk 128GB 存储卡 ×2", created_at: "2026-11-10T10:04:00+08:00", updated_at: "2026-11-10T10:04:00+08:00" },
];

const server = createServer(async (req, res) => {
  try {
    const path = req.url === "/" ? "/index.html" : decodeURIComponent(req.url.split("?")[0]);
    const file = join(DIST, path.replace(/^\/static\//, "").replace(/^\//, ""));
    const body = await readFile(file);
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("not found");
  }
});
await new Promise((r) => server.listen(8765, "127.0.0.1", r));

const mock = (page) =>
  page.route("**/auth/**", (route) => {
    const url = route.request().url();
    const json = (body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (/\/auth\/me\/$/.test(url)) return json(me);
    if (/\/auth\/users\/1\/profile\/$/.test(url)) return json(profile);
    if (/\/auth\/member\/equipment\/$/.test(url)) return json({ limit: 30, items });
    return json({});
  });

const browser = await chromium.launch();
const open = async (opts, theme) => {
  const ctx = await browser.newContext(opts);
  if (theme === "dark") await ctx.addInitScript(() => localStorage.setItem("cobalt:theme", "dark"));
  const page = await ctx.newPage();
  await mock(page);
  await page.goto("http://127.0.0.1:8765/#/u/1?tab=equipment", { waitUntil: "networkidle" });
  await page.waitForSelector(".equip-name", { timeout: 20000 });
  return page;
};

const desktop = await open({ viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 2 });
await desktop.screenshot({ path: "/tmp/equipment-desktop.png", fullPage: true });
await desktop.close();

const dark = await open({ viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 2 }, "dark");
await dark.screenshot({ path: "/tmp/equipment-dark.png", fullPage: true });
await dark.close();

const mobile = await open({
  viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
});
await mobile.screenshot({ path: "/tmp/equipment-mobile.png", fullPage: true });
await mobile.close();

await browser.close();
server.close();
console.log("screenshots ok");
