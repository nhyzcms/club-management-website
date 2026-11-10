import { test, expect } from "@playwright/test";

test("待办：未投票众议以投票债条目呈现", async ({ page }) => {
  await page.goto("/#/inbox");
  await expect(page.getByRole("heading", { name: "待办", level: 1 })).toBeVisible();

  // 「E2E 待办活动」是专供本用例的未投票众议（投票后条目会消失）
  await expect(page.getByText("E2E 待办活动").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".prop-card").first()).toBeVisible();
});
