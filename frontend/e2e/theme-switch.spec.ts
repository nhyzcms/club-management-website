import { test, expect } from "@playwright/test";

/** 昼夜开关（顶栏 / 手机版顶栏）：拟物滑动开关，点击真实切换站点主题。 */
test("昼夜开关：点击在浅色/深色间切换并同步 html[data-theme]", async ({ page }) => {
  await page.goto("/#/");

  const sw = page.getByRole("switch", { name: "深色模式" });
  await expect(sw).toBeVisible({ timeout: 10_000 });

  const html = page.locator("html");
  const before = await html.getAttribute("data-theme");
  const toDark = before !== "dark";

  await sw.click();
  await expect(html).toHaveAttribute("data-theme", toDark ? "dark" : "light");
  await expect(sw).toHaveAttribute("aria-checked", String(toDark));

  // 再点一次切回
  await sw.click();
  await expect(html).toHaveAttribute("data-theme", toDark ? "light" : "dark");
});

test("昼夜开关：键盘可操作（Space 切换）", async ({ page }) => {
  await page.goto("/#/");

  const sw = page.getByRole("switch", { name: "深色模式" });
  await sw.waitFor({ state: "visible", timeout: 10_000 });
  await sw.focus();

  const html = page.locator("html");
  const before = await html.getAttribute("data-theme");

  await page.keyboard.press("Space");
  await expect(html).toHaveAttribute("data-theme", before === "dark" ? "light" : "dark");
});
