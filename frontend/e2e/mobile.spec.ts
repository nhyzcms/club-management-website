import { test, expect } from "@playwright/test";

const MOBILE = {
  userAgent:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
} as const;

test.describe("移动版（匿名）", () => {
  test.use({ ...MOBILE, storageState: { cookies: [], origins: [] } });

  test("访问首页自动跳转手机版并渲染", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/#\/m$/);
    await expect(page.locator(".m-app")).toBeVisible();
  });
});

test.describe("移动版（登录）", () => {
  test.use({ ...MOBILE });

  test("四个页面渲染；我的页显示身份与后台入口", async ({ page }) => {
    await page.goto("/#/m");
    await expect(page.locator(".m-app")).toBeVisible();

    await page.goto("/#/m/news");
    await expect(page.locator(".m-app")).toBeVisible();
    await expect(page.getByText("E2E 种子新闻").first()).toBeVisible({ timeout: 10_000 });

    await page.goto("/#/m/activity");
    await expect(page.locator(".m-app")).toBeVisible();

    await page.goto("/#/m/me");
    await expect(page.locator(".m-app")).toBeVisible();
    await expect(page.getByText("E2E 信息员")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("@e2e_info")).toBeVisible();
    await expect(page.getByText("进入后台管理")).toBeVisible();
  });

  test("详情页：从列表进入新闻 / 活动详情", async ({ page }) => {
    await page.goto("/#/m/news");
    await page.getByText("E2E 种子新闻").first().click();
    await expect(page).toHaveURL(/#\/m\/news\/\d+$/);
    await expect(page.locator(".m-detail-title")).toContainText("E2E 种子新闻");
    await expect(page.getByText("E2E 种子新闻正文，用于列表与详情页断言。")).toBeVisible();

    await page.locator(".m-back").click();
    await expect(page).toHaveURL(/#\/m\/news$/);

    await page.goto("/#/m/activity");
    await page.getByText("E2E 投票活动").first().click();
    await expect(page).toHaveURL(/#\/m\/activity\/\d+$/);
    await expect(page.locator(".m-detail-title")).toContainText("E2E 投票活动");
    // 投票区兼容两态：套件里 activities.spec 先投过票且「全员投完即提前结算」，
    // 此时本页是「已投/已结算」的结果态；单跑本文件时则是未投的选项态。
    await expect(page.locator(".m-detail-sec h3").filter({ hasText: "投票" })).toBeVisible();
    await expect(page.locator(".m-vote-opt, .m-vote-result").first()).toBeVisible();
  });

  test("工作台：桌面路径自动改道到手机版，审核台与任务可直达", async ({ page }) => {
    // 桌面专属页面在手机 UA 下应改道（避免看到未适配宽屏的布局）
    await page.goto("/#/reviews");
    await expect(page).toHaveURL(/#\/m\/review$/);
    await expect(page.getByRole("heading", { name: "审核台" })).toBeVisible();

    const desks = page.getByRole("tablist", { name: "审核类型" });
    await expect(desks.getByRole("button", { name: "身份" })).toBeVisible();
    await expect(desks.getByRole("button", { name: "新闻" })).toBeVisible();
    await expect(desks.getByRole("button", { name: "意见反馈" })).toBeVisible();
    await expect(desks.getByRole("button", { name: "举报案" })).toBeVisible();

    // 任务列表 → 详情（均走手机版路由）
    await page.goto("/#/tasks");
    await expect(page).toHaveURL(/#\/m\/tasks$/);
    const task = page.getByText("E2E 任务：整理素材库").first();
    await expect(task).toBeVisible({ timeout: 10_000 });
    await task.click();
    await expect(page).toHaveURL(/#\/m\/tasks\/\d+$/);
    await expect(page.locator(".mw-detail-title")).toContainText("E2E 任务：整理素材库");

    // 通知：桌面路径同样改道
    await page.goto("/#/notifications");
    await expect(page).toHaveURL(/#\/m\/notifications$/);
    await expect(page.getByRole("heading", { name: "通知" })).toBeVisible();
  });

  test("教程与加入：列表 → 详情 / 公告确认 → 问卷", async ({ page }) => {
    await page.goto("/#/m/tutorials");
    await page.getByText("E2E 教程：投稿指南").first().click();
    await expect(page).toHaveURL(/#\/m\/tutorials\/\d+$/);
    await expect(page.locator(".m-detail-title")).toContainText("E2E 教程：投稿指南");

    await page.goto("/#/m/join");
    await page.getByText("我已阅读并知晓公告内容").click();
    await page.getByRole("button", { name: "立即加入" }).click();
    await expect(page).toHaveURL(/#\/m\/join\/form$/);
    await expect(page.locator(".m-detail-sec .survey-card")).toBeVisible({ timeout: 15_000 });
  });
});
