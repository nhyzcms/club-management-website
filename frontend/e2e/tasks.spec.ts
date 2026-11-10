import { test, expect } from "@playwright/test";
import { uniqueTitle } from "./utils";

test("任务列表：种子任务可见", async ({ page }) => {
  await page.goto("/#/tasks");
  await expect(page.getByRole("heading", { name: "任务", level: 1 })).toBeVisible();
  await expect(page.getByText("E2E 任务：整理素材库").first()).toBeVisible({ timeout: 10_000 });
});

test("任务：新建 → 详情", async ({ page }) => {
  const title = uniqueTitle("E2E 新建任务");

  await page.goto("/#/tasks/new");
  await expect(page.getByRole("heading", { name: "新建任务" })).toBeVisible();
  await page.getByPlaceholder("输入任务标题").fill(title);
  await page.getByRole("button", { name: "创建任务" }).click();

  await page.waitForURL(/#\/tasks\/\d+/);
  await expect(page.getByText(title).first()).toBeVisible();
});
