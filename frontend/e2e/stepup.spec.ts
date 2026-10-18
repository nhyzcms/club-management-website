import { test, expect } from "@playwright/test";

/**
 * 安全验证（Step-up，ADR-0026）E2E。
 * e2e_info 已由 seed 预置安全问题（答案 e2e-answer，不区分大小写/全半角）。
 * 用例：改密码 → 被拦到 /#/verify → 问题作答 → 回跳重试成功 → 凭借 grant 免复验改回
 * （改回同时保护同轮其他用例不受影响）。
 */

test("改密码需安全验证：安全问题作答复验一次，10 分钟内免复验", async ({ page }) => {
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

  // 10 分钟内同 scope 免复验：直接改回，不再跳验证页
  await page.getByLabel("原密码").fill("e2e-new-pass-123");
  await page.getByLabel("新密码", { exact: true }).fill("e2e-pass-123");
  await page.getByLabel("确认新密码").fill("e2e-pass-123");
  await page.getByRole("button", { name: "确认修改" }).click();
  await expect(page.getByText("密码已修改")).toBeVisible();
});

test("安全验证记录：问题验证出现在个人中心「安全验证」", async ({ page }) => {
  await page.goto("/#/profile?tab=security");
  await expect(page.getByRole("heading", { name: "安全验证" })).toBeVisible();
  await expect(page.getByText("最近验证记录")).toBeVisible();
});
