import { test, expect } from "@playwright/test";
import { E2E_PASSWORD, E2E_PLAIN } from "./utils";

// 验证登录流程本身：不使用已登录会话
test.use({ storageState: { cookies: [], origins: [] } });

test("登录弹窗：错误密码给出提示，正确密码进入登录态", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("banner").getByRole("button", { name: "登录" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "登录" })).toBeVisible();

  // 错误密码 → 中文错误提示
  await dialog.getByPlaceholder("请输入信息组分发的用户名").fill(E2E_PLAIN);
  await dialog.getByPlaceholder("请输入密码").fill("wrong-password-123");
  await dialog.getByRole("button", { name: "登录" }).click();
  await expect(dialog.locator(".alert-danger")).toContainText("账号或密码错误");

  // 正确密码 → 弹窗关闭、顶栏进入登录态
  await dialog.getByPlaceholder("请输入密码").fill(E2E_PASSWORD);
  await dialog.getByRole("button", { name: "登录" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("banner").getByRole("button", { name: "打开用户菜单" })).toBeVisible();
});
