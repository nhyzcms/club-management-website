import { test, expect } from "@playwright/test";

// 第五批·动效与细节的回归用例：钉住 transition 显式化与标题 text-wrap。

test("筛选 chip：transition 为显式属性列表（不含 all）", async ({ page }) => {
  await page.goto("/#/news");
  const chip = page.locator(".chip").first();
  await expect(chip).toBeVisible();
  const prop = await chip.evaluate((el) => getComputedStyle(el).transitionProperty);
  expect(prop).not.toContain("all");
  expect(prop).toContain("border-color");
});

test("标题：text-wrap: balance 生效（防孤行）", async ({ page }) => {
  await page.goto("/");
  const h1 = page.locator("h1").first();
  await expect(h1).toBeVisible();
  const wrap = await h1.evaluate((el) => getComputedStyle(el).textWrap);
  expect(wrap).toBe("balance");
});
