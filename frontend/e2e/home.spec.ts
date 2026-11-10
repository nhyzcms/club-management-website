import { test, expect } from "@playwright/test";

test("门户首页：导航、主视觉与社团动态正常渲染", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /用镜头记录青春/ })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link", { name: "新闻" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "任务" })).toBeVisible();

  // 社团动态区异步加载：种子新闻可见
  await expect(page.getByText("E2E 种子新闻").first()).toBeVisible({ timeout: 10_000 });
});

test("首页：导航与侧栏快捷入口跳转", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "主导航" });
  await nav.getByRole("link", { name: "新闻" }).click();
  await expect(page).toHaveURL(/#\/news$/);

  await page.goto("/");
  await page.getByRole("button", { name: "课表下载" }).click();
  await expect(page).toHaveURL(/#\/schedule$/);
});
