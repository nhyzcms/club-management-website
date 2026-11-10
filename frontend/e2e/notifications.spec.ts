import { test, expect } from "@playwright/test";

test("通知：种子通知可见并可全部已读", async ({ page }) => {
  await page.goto("/#/notifications");
  await expect(page.getByRole("heading", { name: "通知", level: 1 })).toBeVisible();

  await expect(page.getByText("内容已通过审核").first()).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "全部已读" }).click();
  await expect(page.getByText("内容已通过审核").first()).toBeVisible();
});
