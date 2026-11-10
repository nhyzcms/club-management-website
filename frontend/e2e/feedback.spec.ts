import { test, expect } from "@playwright/test";
import { uniqueTitle } from "./utils";

test("意见反馈：登录用户提交成功", async ({ page }) => {
  await page.goto("/#/feedback");
  await expect(page.getByRole("heading", { name: "意见反馈", level: 1 })).toBeVisible();

  await page.getByPlaceholder("一句话概括").fill(uniqueTitle("E2E 新反馈"));
  await page.getByPlaceholder("详细描述你的建议或投诉…").fill("E2E 提交的反馈内容。");
  await page.getByRole("button", { name: "匿名提交" }).click();

  await expect(page.locator(".alert-success")).toContainText("已提交，感谢你的反馈！");
});

test("反馈详情：审核人可打开种子反馈", async ({ page }) => {
  const resp = await page.request.get("/reviews/feedbacks/");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  const list = body.results ?? body;
  const item = list.find((x: { title: string }) => x.title === "E2E 反馈条目");
  expect(item).toBeTruthy();

  await page.goto(`/#/feedback/${item.id}`);
  await expect(page.getByRole("heading", { name: "E2E 反馈条目", level: 1 })).toBeVisible();
  await expect(page.getByText("E2E 反馈描述：建议增加暗色模式。")).toBeVisible();
});

test("反馈详情：不存在的反馈给出兜底提示", async ({ page }) => {
  await page.goto("/#/feedback/999999");
  await expect(page.locator(".empty-text")).toContainText(/No Feedback matches|反馈不存在或无权查看/);
});
