import { test, expect } from "@playwright/test";
import { pngBuffer, uniqueTitle } from "./utils";

test("编辑器插图：工具栏「图片」上传并插入正文", async ({ page }) => {
  await page.goto("/#/news/new");
  await page.getByPlaceholder("新闻标题…").fill(uniqueTitle("E2E 插图"));
  await page.locator(".rte-content").click();

  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByRole("button", { name: "图片" }).click(),
  ]);
  await chooser.setFiles({ name: "inline.png", mimeType: "image/png", buffer: pngBuffer() });

  await expect(page.locator('.rte-content img[src*="news_content_images"]')).toBeVisible({ timeout: 15_000 });
});
