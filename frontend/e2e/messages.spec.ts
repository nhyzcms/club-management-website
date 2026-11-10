import { test, expect } from "@playwright/test";
import { uniqueTitle } from "./utils";

test("私信：会话列表与种子消息", async ({ page }) => {
  await page.goto("/#/messages");
  await expect(page.getByRole("heading", { name: "私信", level: 1 })).toBeVisible();

  const conv = page.getByText(/E2E 会话|E2E 普通成员/).first();
  await expect(conv).toBeVisible({ timeout: 10_000 });
  await conv.click();

  // 同一文案出现在两处：列表预览（div.ml-preview）+ 会话气泡（span），分别断言
  await expect(page.locator(".ml-preview")).toContainText("E2E 私信：你好，这是种子消息。");
  await expect(
    page.locator("span", { hasText: "E2E 私信：你好，这是种子消息。" }).first(),
  ).toBeVisible({ timeout: 10_000 });
});

test("私信：发送消息", async ({ page }) => {
  await page.goto("/#/messages");
  const conv = page.getByText(/E2E 会话|E2E 普通成员/).first();
  await expect(conv).toBeVisible({ timeout: 10_000 });
  await conv.click();

  const text = uniqueTitle("E2E 发送");
  await page.getByPlaceholder(/输入消息/).fill(text);
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.locator("span", { hasText: text }).first()).toBeVisible({ timeout: 10_000 });
});
