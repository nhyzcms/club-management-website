import { test, expect } from "@playwright/test";

test("考试看板：页面加载、时间表与考试信息", async ({ page }) => {
  await page.goto("/#/exam");
  await expect(page).toHaveTitle(/考试看板/);

  // 首次进入显示监考指南浮层：等待渲染后关闭（否则会拦截后续点击）
  const guideOk = page.getByRole("button", { name: "知道了" });
  await guideOk.waitFor({ state: "visible", timeout: 8_000 }).catch(() => {});
  if (await guideOk.isVisible().catch(() => false)) {
    await guideOk.click();
    await expect(page.locator(".board-guide")).toBeHidden();
  }

  await expect(page.getByRole("complementary", { name: "考试时间表" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("E2E 期中考试").first()).toBeVisible();

  // 展开时间表后可见科目
  await page.getByRole("button", { name: /时间表 高一/ }).click();
  await expect(page.getByText("语文").first()).toBeVisible({ timeout: 10_000 });
});
