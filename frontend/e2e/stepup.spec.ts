import { test, expect } from "@playwright/test";

/**
 * 安全验证（Step-up，ADR-0026）E2E。
 *
 * 改密用例使用**专属账号 e2e_stepup**（seed 预置，含安全问题「你小学的名称是？」答案 e2e-answer）：
 * 改密成功会轮换 session key（update_session_auth_hash 防会话固定），若拿共享 storageState 的
 * e2e_info 做改密，会让其后所有用例的登录态失效——故本用例独立会话、独立账号。
 * 流程：改密码 → 被拦到 /#/verify → 问题作答 → 回跳重试成功 → 凭借 grant 免复验改回（同时还原密码）。
 */

test.describe("改密安全验证（独立账号 e2e_stepup）", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("改密码需安全验证：安全问题作答复验一次，10 分钟内免复验", async ({ page }) => {
    // API 登录专属账号（独立会话）
    await page.goto("/");
    await page.request.get("/auth/csrf/");
    const csrf = (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value ?? "";
    const resp = await page.request.post("/auth/login/", {
      headers: { "X-CSRFToken": csrf },
      data: { username: "e2e_stepup", password: "e2e-pass-123" },
    });
    expect(resp.ok()).toBeTruthy();

    await page.goto("/#/profile?tab=password");
    await expect(page.getByRole("button", { name: "确认修改" })).toBeVisible();

    // 第一次提交 → 无 grant → 跳转验证页
    await page.getByLabel("原密码").fill("e2e-pass-123");
    await page.getByLabel("新密码", { exact: true }).fill("e2e-new-pass-123");
    await page.getByLabel("确认新密码").fill("e2e-new-pass-123");
    await page.getByRole("button", { name: "确认修改" }).click();

    await expect(page.getByRole("heading", { name: "安全验证" })).toBeVisible();
    await page.getByRole("tab", { name: "安全问题" }).click();
    await page.getByLabel("答案").fill("E2E-Answer"); // 归一化：不区分大小写
    await page.getByRole("button", { name: "完成验证并继续" }).click();

    // 回跳密码面板 → 重试成功
    await expect(page.getByRole("button", { name: "确认修改" })).toBeVisible();
    await page.getByLabel("原密码").fill("e2e-pass-123");
    await page.getByLabel("新密码", { exact: true }).fill("e2e-new-pass-123");
    await page.getByLabel("确认新密码").fill("e2e-new-pass-123");
    await page.getByRole("button", { name: "确认修改" }).click();
    await expect(page.getByText("密码已修改")).toBeVisible();

    // 10 分钟内同 scope 免复验：直接改回，不再跳验证页（同时还原密码）
    await page.getByLabel("原密码").fill("e2e-new-pass-123");
    await page.getByLabel("新密码", { exact: true }).fill("e2e-pass-123");
    await page.getByLabel("确认新密码").fill("e2e-pass-123");
    await page.getByRole("button", { name: "确认修改" }).click();
    await expect(page.getByText("密码已修改")).toBeVisible();
  });
});

test("安全验证记录：个人中心「安全验证」面板可见", async ({ page }) => {
  await page.goto("/#/profile?tab=security");
  await expect(page.getByRole("heading", { name: "安全验证" })).toBeVisible();
  await expect(page.getByText("最近验证记录")).toBeVisible();
});
