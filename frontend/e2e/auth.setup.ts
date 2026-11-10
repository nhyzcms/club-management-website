import { test as setup, expect } from "@playwright/test";
import { E2E_PASSWORD, E2E_USER } from "./utils";

const AUTH_FILE = "e2e/.auth/info.json";

/** 以信息组账号登录一次并保存会话；chromium 项目的用例复用该登录态。 */
setup("登录信息组账号并保存会话", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("banner").getByRole("button", { name: "登录" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByPlaceholder("请输入信息组分发的用户名").fill(E2E_USER);
  await dialog.getByPlaceholder("请输入密码").fill(E2E_PASSWORD);
  await dialog.getByRole("button", { name: "登录" }).click();

  await expect(page.getByRole("banner").getByRole("button", { name: "打开用户菜单" })).toBeVisible();
  await page.context().storageState({ path: AUTH_FILE });
});
