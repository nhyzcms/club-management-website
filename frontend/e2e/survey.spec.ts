import { test, expect } from "@playwright/test";

// 顺序约定：问卷一旦有作答，schema 锁定、「编辑问卷」入口消失。
// 本文件按此依赖执行：① 编辑入口（零作答）→ ② 提交一份作答 → ③ 结果/统计页。

test("调研活动：编辑问卷入口打开编辑器（零作答时可用）", async ({ page }) => {
  await page.goto("/#/activity");
  await page.getByText("E2E 调研活动").first().click();
  await expect(page.getByRole("heading", { name: "E2E 调研活动", level: 1 })).toBeVisible();

  await page.getByRole("button", { name: "编辑问卷" }).first().click();
  await expect(page).toHaveURL(/survey-edit/);
  await expect(page.getByRole("heading", { name: "编辑问卷", level: 1 })).toBeVisible({ timeout: 15_000 });
});

test("调研活动：填写问卷并提交", async ({ page }) => {
  await page.goto("/#/activity");
  await page.getByText("E2E 调研活动").first().click();
  await expect(page.getByRole("heading", { name: "E2E 调研活动", level: 1 })).toBeVisible();

  // 问卷组件渲染后：选择单选 + 完成提交
  const card = page.locator(".survey-card");
  await expect(card).toBeVisible({ timeout: 10_000 });
  await card.getByText("新闻", { exact: true }).click();
  await card.getByRole("button", { name: "提交问卷" }).click();

  await expect(page.getByText("你已经提交过了。")).toBeVisible({ timeout: 10_000 });
});

test("调研活动：结果页与统计页", async ({ page }) => {
  await page.goto("/#/activity");
  await page.getByText("E2E 调研活动").first().click();
  await expect(page.getByRole("heading", { name: "E2E 调研活动", level: 1 })).toBeVisible();

  // 查看结果：已有 1 份作答，不是空态
  await page.getByRole("button", { name: "查看结果" }).click();
  await expect(page).toHaveURL(/survey-responses/);
  await expect(page.getByRole("heading", { name: "问卷结果", level: 1 })).toBeVisible();
  await expect(page.getByText("暂无作答。")).toHaveCount(0);

  // 检索作答内容：命中选择题选项文本 → 1 份；无命中 → 空态；清空 → 回到全部
  const searchBox = page.getByRole("searchbox", { name: "搜索作答内容" });
  await searchBox.fill("新闻");
  await expect(page.getByText(/匹配 1 份/)).toBeVisible({ timeout: 10_000 });
  await searchBox.fill("绝对不存在的答案");
  await expect(page.getByText("没有匹配的作答。")).toBeVisible({ timeout: 10_000 });
  await searchBox.fill("");
  await expect(page.getByText(/共 1 份作答/)).toBeVisible({ timeout: 10_000 });

  // 查看统计
  await page.goto("/#/activity");
  await page.getByText("E2E 调研活动").first().click();
  await page.getByRole("button", { name: "查看统计" }).click();
  await expect(page).toHaveURL(/survey-stats/);
  await expect(page.getByRole("heading", { name: "问卷统计", level: 1 })).toBeVisible();
});

