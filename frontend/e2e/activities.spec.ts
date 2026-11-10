import { test, expect } from "@playwright/test";

test("活动列表：类型筛选与种子活动可见", async ({ page }) => {
  await page.goto("/#/activity");
  await expect(page.getByRole("heading", { name: "活动", level: 1 })).toBeVisible();
  await expect(page.getByText("E2E 投票活动").first()).toBeVisible({ timeout: 10_000 });

  // 切到「调研」筛选：调研活动可见
  const tabs = page.getByRole("tablist", { name: "活动类型" });
  await tabs.getByRole("button", { name: "调研" }).click();
  await expect(page.getByText("E2E 调研活动").first()).toBeVisible({ timeout: 10_000 });
});

test("活动详情：公开众议投票", async ({ page }) => {
  await page.goto("/#/activity");
  await page.getByText("E2E 投票活动").first().click();

  await expect(page.getByRole("heading", { name: "E2E 投票活动", level: 1 })).toBeVisible();
  await expect(page.getByText("E2E 投票活动正文：请选择你支持的一项。")).toBeVisible();

  await page.getByText("选项甲").click();
  await page.getByRole("button", { name: "投票" }).click();

  await expect(page.getByText(/你投了：选项甲/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/共 1 人投票/)).toBeVisible();
});
