import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test, expect } from "@playwright/test";

/**
 * 社员身份（Part A / ADR-0025）E2E：
 * - 注册后的「以下身份是否是你」认领阶段（选身份 + 手机号后四位 → 绑定）；
 * - 公开扫码校验页 /#/v/:code?s=…（有效签名 / 签名不符）。
 *
 * 夹具来自 seed_e2e（每次 e2e-server 重建数据库时写出）：
 * frontend/e2e/.member-qr.json = { code, sig, name }（「谢二」，第 9 届·信息）。
 */
const qr = JSON.parse(
  readFileSync(join(process.cwd(), "e2e", ".member-qr.json"), "utf-8"),
) as { code: string; sig: string; name: string };

test.use({ storageState: { cookies: [], origins: [] } });

test("注册 → 认领阶段：选身份 + 手机号后四位 → 认领成功", async ({ page }) => {
  await page.goto("/#/register");
  await expect(page.getByRole("heading", { name: "注册账号" })).toBeVisible();

  await page.getByPlaceholder("登录用用户名").fill(`e2e_claim_${Date.now()}`);
  await page.getByPlaceholder("至少 8 位").fill("e2e-claim-123456");
  await page.getByPlaceholder("再输一次").fill("e2e-claim-123456");
  await page.getByPlaceholder("用于身份核验，不公开展示").fill(qr.name);
  await page.locator("select").selectOption({ index: 1 });
  await page.getByRole("button", { name: "注册" }).click();

  // 注册即登录 → 账号有效期弹窗（ADR-0041）会盖住页面；新账号从未读过，必弹。
  const validity = page.getByRole("alertdialog", { name: "账号有效期" });
  await expect(validity).toBeVisible();
  await validity.getByRole("button", { name: "我知道了" }).click();
  await expect(validity).toBeHidden();

  // 注册即登录 → 进入认领阶段
  await expect(page.getByRole("heading", { name: "以下身份是否是你？" })).toBeVisible();
  await expect(page.getByText("第 9 届")).toBeVisible();

  await page.getByLabel("手机号后四位").fill("1234");
  await page.getByRole("button", { name: "确认绑定" }).click();
  await expect(page.getByRole("heading", { name: "认领成功" })).toBeVisible();
});

test("扫码校验页：有效签名展示社员信息", async ({ page }) => {
  await page.goto(`/#/v/${qr.code}?s=${qr.sig}`);
  await expect(page.getByText(qr.name)).toBeVisible();
  await expect(page.getByText("第 9 届")).toBeVisible();
  await expect(page.getByText(`识别码 ${qr.code}`)).toBeVisible();
});

test("扫码校验页：签名不符时统一提示无效", async ({ page }) => {
  await page.goto(`/#/v/${qr.code}?s=deadbeef`);
  await expect(page.getByText(/未找到匹配的社员身份/)).toBeVisible();
});
