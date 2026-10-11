import { test, expect } from "@playwright/test";

test("关于页：标题、区块目录与首块默认展开", async ({ page }) => {
  await page.goto("/#/about");

  await expect(page.getByRole("heading", { name: "关于我们", level: 1 })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "关于区块" })).toBeVisible();

  // 首块「社团简介」默认展开：种子正文无需点击即可见
  await expect(page.getByText("E2E 社团简介正文。")).toBeVisible();
});
