import { test, expect } from "@playwright/test";
import { pngBuffer, uniqueTitle } from "./utils";

test("新闻封面两段式：选完即传 → 发布展示 → 移除清除", async ({ page }) => {
  const title = uniqueTitle("E2E 封面流程");
  await page.goto("/#/news/new");
  await page.getByPlaceholder("新闻标题…").fill(title);

  // ① 选图即传：预览直接使用服务端 news_covers/ URL（而非本地 blob）
  await page.locator('.compose-meta input[type="file"]').setInputFiles({
    name: "cover.png",
    mimeType: "image/png",
    buffer: pngBuffer(),
  });
  const preview = page.locator(".compose-cover img");
  await expect(preview).toBeVisible({ timeout: 15_000 });
  await expect(preview).toHaveAttribute("src", /\/media\/news_covers\/[0-9a-f]{32}\.png$/);

  // ② 发布 → 详情页头图可见
  await page.locator(".compose-actions .btn-primary").click();
  await page.waitForURL(/#\/news\/\d+$/);
  await expect(page.locator(".article-hero img")).toBeVisible();
  const id = (page.url().match(/#\/news\/(\d+)$/) as RegExpMatchArray)[1];

  // ③ 编辑 → 移除 → 保存 → 封面被真正清除（头图回落占位）
  await page.goto(`/#/news/${id}/edit`);
  await page.getByRole("button", { name: "移除" }).click();
  await page.locator(".compose-actions .btn-primary").click();
  await page.waitForURL(new RegExp(`#/news/${id}$`));
  await expect(page.locator(".article-hero.ph-img")).toBeVisible();
});
