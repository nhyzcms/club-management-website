import { test, expect } from "@playwright/test";

test("未知路由：兜底重定向回首页", async ({ page }) => {
  await page.goto("/#/no-such-page-xyz");
  await expect(page).toHaveURL(/#\/$/, { timeout: 10_000 });
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
});

test("互动：发起互动表单", async ({ page }) => {
  await page.goto("/#/activity/new");
  await expect(page.getByRole("heading", { name: "发起互动", level: 1 })).toBeVisible({ timeout: 10_000 });
});

test("教程：上传教程表单", async ({ page }) => {
  await page.goto("/#/tutorials/new");
  await expect(page.getByRole("heading", { name: "上传教程", level: 1 })).toBeVisible({ timeout: 10_000 });
});

test("任务：编辑任务表单", async ({ page }) => {
  await page.goto("/#/tasks/1/edit");
  await expect(page.getByRole("heading", { name: "编辑任务", level: 1 })).toBeVisible({ timeout: 10_000 });
});

test("邮箱认证：无效链接兜底与重发页", async ({ page }) => {
  await page.goto("/#/verify-email");
  await expect(page.getByRole("heading", { name: "认证失败" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "重新发送认证邮件" })).toBeVisible();

  await page.goto("/#/verify-email-pending");
  await expect(page.getByRole("heading", { name: "重发认证邮件" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "发送认证邮件" })).toBeVisible();
});
