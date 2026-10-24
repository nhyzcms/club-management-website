import { test, expect } from "@playwright/test";

/**
 * 登录设备（多端登录，ADR-0028）。
 *
 * 2026-10-24 起统一收进账号安全中心：个人中心的「登录设备」tab 已移除，
 * 名额信息（在线 N / 上限）与设备列表都在 /#/security。
 *
 * 只做只读断言：e2e 主账号由 auth.setup 登录一次，seed_e2e 已清空设备记录，
 * 所以这里必然是「在线 1 / 3」且本机不出现「退出」按钮（避免自踢造成后续用例掉线）。
 */
test.describe("登录设备", () => {
  test("安全中心显示在线名额与本机设备", async ({ page }) => {
    await page.goto("/#/security");

    await expect(page.getByTestId("device-quota")).toContainText("在线 1 / 3");
    await expect(page.getByText("当前", { exact: true })).toBeVisible();
    // 本机是唯一设备时不出现「退出」按钮，避免把 e2e 自己踢下线
    await expect(page.getByRole("button", { name: "退出", exact: true })).toHaveCount(0);
  });
});
