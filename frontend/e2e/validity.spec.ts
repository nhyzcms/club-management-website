import { test, expect } from "@playwright/test";
import { E2E_PASSWORD } from "./utils";

// 专属账号 e2e_validity 从不预置「已读」：登录后必弹「账号有效期」。
// 不用共享 storageState（那是 e2e_info 的会话）。
test.use({ storageState: { cookies: [], origins: [] } });

test("账号有效期：登录后弹窗展示到期时间、剩余有效期与规则，已读后不再打扰", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("banner").getByRole("button", { name: "登录" }).click();

  const login = page.getByRole("dialog");
  await login.getByPlaceholder("请输入信息组分发的用户名").fill("e2e_validity");
  await login.getByPlaceholder("请输入密码").fill(E2E_PASSWORD);
  await login.getByRole("button", { name: "登录" }).click();

  const modal = page.getByRole("alertdialog", { name: "账号有效期" });
  await expect(modal).toBeVisible();
  await expect(modal.getByText("认证截止时间")).toBeVisible();
  await expect(modal.getByText("剩余有效期")).toBeVisible();
  await expect(modal.getByText(/注册宽限 \d+ 天/)).toBeVisible();

  // 点「我知道了」→ 写回服务端（Profile.validity_notice_ack）；刷新后不再弹。
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/auth/validity/ack/") && r.request().method() === "POST",
    ),
    modal.getByRole("button", { name: "我知道了" }).click(),
  ]);
  await expect(modal).toBeHidden();

  await page.reload();
  await expect(page.getByRole("alertdialog", { name: "账号有效期" })).toHaveCount(0);
});
