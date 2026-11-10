import { test, expect } from "@playwright/test";

test("加入社团：公告勾选后进入自我介绍问卷并提交", async ({ page }) => {
  await page.goto("/#/join");
  await expect(page.getByRole("heading", { name: "加入社团", level: 1 })).toBeVisible();
  await expect(page.getByText("欢迎加入南汇一中传媒社（E2E 招生公告）。")).toBeVisible();

  // 未勾选时「立即加入」不可点
  const joinBtn = page.getByRole("button", { name: "立即加入" });
  await expect(joinBtn).toBeDisabled();

  await page.getByRole("checkbox").check();
  await joinBtn.click();

  await expect(page).toHaveURL(/#\/join\/form$/);
  await expect(page.getByRole("heading", { name: "自我介绍问卷" })).toBeVisible();

  // 填写必填项：年级 + 自我介绍，提交
  const card = page.locator(".survey-card");
  await expect(card).toBeVisible({ timeout: 10_000 });
  await card.getByText("高一", { exact: true }).click();
  await card.locator("textarea").fill("E2E 自我介绍：热爱摄影与剪辑。");
  await card.getByRole("button", { name: "提交问卷" }).click();

  // 提交成功页
  await expect(page.getByRole("button", { name: "返回首页" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/已提交 1 次/)).toBeVisible();
});

test("加入社团：编辑入口（信息组）", async ({ page }) => {
  await page.goto("/#/join");
  await expect(page.getByRole("button", { name: "编辑问卷" })).toBeVisible();
  await page.getByRole("button", { name: "编辑问卷" }).click();
  await expect(page).toHaveURL(/#\/join\/editor$/);
});
