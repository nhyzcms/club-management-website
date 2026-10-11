import { test, expect } from "@playwright/test";

// 第四批·表单体验（autocomplete / 错误聚焦 / 标签关联）的回归用例：
// 钉住最容易被误改回去的行为——字段 autocomplete 提示、标签点击聚焦、校验失败聚焦首错字段。

test.describe("匿名表单（登录 / 注册 / 忘记密码）", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("登录弹窗：账号与密码字段带 autocomplete，表单不再整体 off", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("banner").getByRole("button", { name: "登录" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.locator("#auth-account")).toHaveAttribute("autocomplete", "username");
    await expect(dialog.locator("#auth-password")).toHaveAttribute("autocomplete", "current-password");
    // 表单级 off 会阻止密码管理器工作，已移除
    await expect(dialog.locator("#auth-form")).not.toHaveAttribute("autocomplete", "off");
  });

  test("注册页：标签点击聚焦 + 用户名 autocomplete/spellcheck", async ({ page }) => {
    await page.goto("/#/register");
    await expect(page.getByRole("heading", { name: "注册账号" })).toBeVisible();
    await page.locator('label[for="reg-username"]').click();
    await expect(page.locator("#reg-username")).toBeFocused();
    await expect(page.locator("#reg-username")).toHaveAttribute("autocomplete", "username");
    await expect(page.locator("#reg-username")).toHaveAttribute("spellcheck", "false");
  });

  test("忘记密码页：标签点击聚焦 + 邮箱 autocomplete", async ({ page }) => {
    await page.goto("/#/forgot-password");
    await expect(page.getByRole("heading", { name: "忘记密码" })).toBeVisible();
    await page.locator('label[for="fp-email"]').click();
    await expect(page.locator("#fp-email")).toBeFocused();
    await expect(page.locator("#fp-email")).toHaveAttribute("autocomplete", "email");
  });
});

test.describe("登录态表单（改密面板）", () => {
  test("改密面板：两次密码不一致时聚焦确认框", async ({ page }) => {
    await page.goto("/#/profile");
    await expect(page).toHaveURL(/#\/u\/\d+/);
    const uid = (page.url().match(/#\/u\/(\d+)/) || [])[1];
    await page.goto(`/#/u/${uid}?tab=password`);
    await expect(page.locator("#pw-old")).toBeVisible();

    await page.locator("#pw-old").fill("e2e-wrong-old-1");
    await page.locator("#pw-new").fill("e2e-new-pass-123");
    await page.locator("#pw-confirm").fill("e2e-new-pass-456");
    await page.getByRole("button", { name: "确认修改" }).click();

    await expect(page.locator(".alert-danger")).toContainText("两次输入的密码不一致");
    await expect(page.locator("#pw-confirm")).toBeFocused();
  });
});
