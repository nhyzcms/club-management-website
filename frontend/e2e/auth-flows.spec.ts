import { test, expect } from "@playwright/test";
import { E2E_USER } from "./utils";

// 认证相关页面均为匿名态：不加载已登录会话
test.use({ storageState: { cookies: [], origins: [] } });

test("注册页：客户端预检——两次密码不一致 / 密码过短", async ({ page }) => {
  await page.goto("/#/register");
  await expect(page.getByRole("heading", { name: "注册账号" })).toBeVisible();

  await page.getByPlaceholder("登录用用户名").fill("e2e_tmp_user");
  await page.getByPlaceholder("用于身份核验，不公开展示").fill("测试姓名");
  await page.locator("select").selectOption({ index: 1 });

  // ① 两次密码不一致
  await page.getByPlaceholder("至少 8 位").fill("e2e-tmp-123456");
  await page.getByPlaceholder("再输一次").fill("e2e-tmp-654321");
  await page.getByRole("button", { name: "注册" }).click();
  await expect(page.locator(".alert-danger")).toContainText("两次输入的密码不一致。");

  // ② 密码过短
  await page.getByPlaceholder("至少 8 位").fill("short");
  await page.getByPlaceholder("再输一次").fill("short");
  await page.getByRole("button", { name: "注册" }).click();
  await expect(page.locator(".alert-danger")).toContainText("密码至少 8 位。");
});

test("忘记密码：提交后给出防探测提示", async ({ page }) => {
  await page.goto("/#/forgot-password");
  await expect(page.getByRole("heading", { name: "忘记密码" })).toBeVisible();

  await page.getByPlaceholder("请输入注册邮箱").fill(`${E2E_USER}@example.test`);
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator(".alert-success")).toContainText("重置链接已发送");
});

test("重置密码：无有效 token 时提示链接无效", async ({ page }) => {
  await page.goto("/#/reset-password");
  await expect(page.getByRole("heading", { name: "链接无效" })).toBeVisible();
  await expect(page.getByText("该密码重置链接无效或已过期。")).toBeVisible();
});

test("邮箱认证：无有效参数时提示认证失败", async ({ page }) => {
  await page.goto("/#/verify-email");
  await expect(page.getByRole("heading", { name: "认证失败" })).toBeVisible();
  await expect(page.getByText("该认证链接无效或已过期。")).toBeVisible();
});

test("重发认证邮件：提交后给出成功提示", async ({ page }) => {
  await page.goto("/#/verify-email-pending");
  await expect(page.getByRole("heading", { name: "重发认证邮件" })).toBeVisible();

  await page.getByPlaceholder("请输入注册时的邮箱").fill("e2e_plain@example.test");
  await page.locator('form button[type="submit"]').click();
  await expect(page.locator(".alert-success")).toBeVisible();
});
