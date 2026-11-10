import { test, expect } from "@playwright/test";

test("审核台：发布审核桌通过待审新闻（自动前进）", async ({ page }) => {
  await page.goto("/#/reviews");
  await expect(page.getByRole("heading", { name: "审核台", level: 1 })).toBeVisible();

  const desks = page.getByRole("tablist", { name: "审核类型" });
  await desks.getByRole("button", { name: "新闻" }).click();

  const first = page.getByText(/E2E 待审新闻[甲乙]/).first();
  await expect(first).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "通过", exact: true }).click();
  await expect(page.getByText("已通过").first()).toBeVisible({ timeout: 10_000 });
});

test("审核台：意见反馈 / 举报案 / 身份 三桌可见", async ({ page }) => {
  await page.goto("/#/reviews");
  await expect(page.getByRole("heading", { name: "审核台", level: 1 })).toBeVisible();
  const desks = page.getByRole("tablist", { name: "审核类型" });

  // 意见反馈桌：种子反馈（匿名提交）
  await desks.getByRole("button", { name: "意见反馈" }).click();
  await expect(page.getByText("E2E 反馈条目")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/提交人 匿名/)).toBeVisible();

  // 举报案桌：不是空队列
  await desks.getByRole("button", { name: "举报案" }).click();
  await expect(page.locator(".desk-pane")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("本队列已空")).toHaveCount(0);

  // 身份桌：e2e_plain 的待审认证 + 操作按钮
  await desks.getByRole("button", { name: "身份" }).click();
  await expect(page.getByText("e2e_plain").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "通过", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下一条" })).toBeVisible();
});
