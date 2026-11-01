import { test, expect } from "@playwright/test";

// 回归：活动「发起」表单里就该能设计问卷（此前只能在创建后到详情页的「编辑问卷」补题）。
// 这里覆盖入口与弹层（SurveyJS Creator 按需加载、portal 到 body 不干扰表单提交）；
// 题目保存逻辑由 src/pages/__tests__/ActivityFormPage.test.tsx 覆盖。
test("调研：发起页可直接打开问卷设计弹层", async ({ page }) => {
  await page.goto("/#/activity/new");
  await expect(page.getByRole("heading", { name: "发起互动", level: 1 })).toBeVisible();

  // 切到调研：问卷设计区块出现，默认空表
  await page.getByRole("button", { name: "调研（问卷）" }).click();
  await expect(page.getByText("尚未添加题目")).toBeVisible();
  await expect(page.getByText("题目会随「发起互动」一起创建")).toBeVisible();

  // 打开设计弹层：Creator 首次加载较慢（独立 chunk），等工具箱渲染
  await page.getByRole("button", { name: "设计问卷" }).click();
  const dialog = page.getByRole("dialog", { name: "设计问卷" });
  await expect(dialog).toBeVisible({ timeout: 30_000 });
  await expect(dialog.locator(".svc-toolbox__item").first()).toBeVisible({ timeout: 30_000 });

  // 关闭后回到表单，标题仍在、可继续提交
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("尚未添加题目")).toBeVisible();
});
