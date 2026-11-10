import { test, expect } from "@playwright/test";

test("新闻列表：搜索种子新闻并进入详情", async ({ page }) => {
  await page.goto("/#/news");
  await expect(page.getByRole("heading", { name: "新闻", level: 1 })).toBeVisible();

  // 搜索定位到种子新闻（避免受其他用例创建的数据影响）
  await page.getByLabel("搜索新闻").fill("E2E 种子新闻");
  const item = page.getByRole("heading", { name: "E2E 种子新闻" }).first();
  await expect(item).toBeVisible({ timeout: 10_000 });

  await item.click();
  await expect(page).toHaveURL(/#\/news\/\d+$/);
  await expect(page.getByRole("heading", { name: "E2E 种子新闻", level: 1 })).toBeVisible();
  await expect(page.getByText("E2E 种子新闻正文，用于列表与详情页断言。")).toBeVisible();
});

test("新闻详情：不存在的新闻给出兜底提示", async ({ page }) => {
  await page.goto("/#/news/999999");
  await expect(page.locator(".news-empty")).toContainText(/No News matches|新闻不存在或已下线/);
});
