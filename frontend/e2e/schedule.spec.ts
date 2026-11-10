import { test, expect } from "@playwright/test";

test("课表下载：标题与各班级下载链接完整渲染", async ({ page }) => {
  await page.goto("/#/schedule");

  await expect(page.getByRole("heading", { name: "课表下载", level: 1 })).toBeVisible();
  await expect(page.getByText("点击下载ClassIsland快速使用指南")).toBeVisible();
  await expect(page.getByText("点击下载高一1班课程表文件")).toBeVisible();
  await expect(page.getByText("点击下载高三8班课程表文件")).toBeVisible();

  // 静态下载链接（ClassIsland 指南/压缩包 + 三个年级 × 8 个班级）
  const links = page.locator('a[href^="/file/"]');
  expect(await links.count()).toBeGreaterThanOrEqual(24);
});
