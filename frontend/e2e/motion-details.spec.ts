import { test, expect } from "@playwright/test";

// 第五批·动效与细节的回归用例：钉住 transition 显式化与标题 text-wrap。

test("筛选 chip：transition 为显式属性列表（不含 all）", async ({ page }) => {
  await page.goto("/#/news");
  const chip = page.locator(".chip").first();
  await expect(chip).toBeVisible();
  // 用可重试的 toHaveCSS 代替一次性 evaluate：新闻列表数据到达时会重渲染，
  // 单次读 computed style 可能撞上尚未定型的样式（实测读回空串 → main 上偶发红），
  // 重试即稳定；语义与原来一致（含 border-color、不含 all）。
  await expect(chip).toHaveCSS("transition-property", /border-color/);
  await expect(chip).not.toHaveCSS("transition-property", /\ball\b/);
});

test("标题：text-wrap: balance 生效（防孤行）", async ({ page }) => {
  await page.goto("/");
  const h1 = page.locator("h1").first();
  await expect(h1).toBeVisible();
  const wrap = await h1.evaluate((el) => getComputedStyle(el).textWrap);
  expect(wrap).toBe("balance");
});
