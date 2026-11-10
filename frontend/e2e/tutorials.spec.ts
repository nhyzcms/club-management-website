import { test, expect } from "@playwright/test";

test("教程集锦：列表 → 文档详情", async ({ page }) => {
  await page.goto("/#/tutorials");
  await expect(page.getByRole("heading", { name: "常用教程集锦", level: 1 })).toBeVisible();

  const item = page.getByRole("heading", { name: "E2E 教程：投稿指南" }).first();
  await expect(item).toBeVisible({ timeout: 10_000 });
  await item.click();

  await expect(page).toHaveURL(/#\/tutorials\/\d+$/);
  await expect(page.getByRole("heading", { name: "E2E 教程：投稿指南", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: /下载文档/ })).toBeVisible();
});
