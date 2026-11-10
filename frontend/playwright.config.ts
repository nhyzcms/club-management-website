import { defineConfig, devices } from "@playwright/test";

/**
 * 浏览器 E2E（Playwright / chromium）配置。
 *
 * 运行前提：
 *  1. 前端产物已构建：cd frontend && npm run build（Django 直接托管 frontend/dist）；
 *  2. 浏览器已安装：npx playwright install chromium --with-deps（首次）。
 *
 * webServer 调用 scripts/e2e-server.sh：独立数据库（run/e2e.sqlite3，每次重建）→
 * migrate → seed_e2e → Django runserver（127.0.0.1:8010，托管 SPA / API / media）。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  // 单进程 Django + SQLite：串行执行，避免写锁与状态竞争
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:8010",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    // 登录一次并保存会话（storageState），供 chromium 项目的用例复用
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      testMatch: /.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/info.json" },
      dependencies: ["setup"],
    },
  ],
  webServer: {
    command: "bash ../scripts/e2e-server.sh",
    url: "http://127.0.0.1:8010/",
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
