import { test, expect } from "@playwright/test";

/**
 * 登录设备（多端登录，ADR-0028）。
 *
 * 只做只读断言：e2e 主账号由 auth.setup 登录一次，seed_e2e 已清空设备记录，
 * 所以这里必然是「在线 1 / 3」且本机无「下线」按钮（避免自踢造成后续用例掉线）。
 */
test.describe("登录设备", () => {
  test("个人中心显示名额与本机设备", async ({ page }) => {
    await page.goto("/#/profile?tab=sessions");

    await expect(page.getByRole("heading", { name: "登录设备" })).toBeVisible();
    await expect(page.getByText(/在线 1 \/ 3/)).toBeVisible();
    await expect(page.getByText("本机")).toBeVisible();
    // 只有一台设备时不需要「下线其他所有设备」，本机也不出现「下线」按钮
    await expect(page.getByRole("button", { name: "下线其他所有设备" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "下线", exact: true })).toHaveCount(0);
  });
});
