import { test, expect } from "@playwright/test";

test("个人资料：/profile 重定向到我的主页", async ({ page }) => {
  await page.goto("/#/profile");
  await expect(page).toHaveURL(/#\/u\/\d+$/);
  await expect(page.getByText("E2E 信息员").first()).toBeVisible({ timeout: 10_000 });
});

test("用户主页：他人主页标签与不存在用户兜底", async ({ page }) => {
  // e2e_plain 是种子里的第二个账号（id=2）：非本人视角展示「ta 的新闻」等标签
  await page.goto("/#/u/2");
  await expect(page.getByText("ta 的新闻")).toBeVisible({ timeout: 10_000 });

  await page.goto("/#/u/999999");
  await expect(page.getByText("用户不存在。")).toBeVisible();
});
