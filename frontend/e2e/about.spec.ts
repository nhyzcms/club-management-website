import { test, expect } from "@playwright/test";

test("关于页：标题、区块目录与首块默认展开", async ({ page }) => {
  await page.goto("/#/about");

  await expect(page.getByRole("heading", { name: "关于我们", level: 1 })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "关于区块" })).toBeVisible();

  // 首块「社团简介」默认展开：种子正文无需点击即可见
  await expect(page.getByText("E2E 社团简介正文。")).toBeVisible();
});

test("关于页：悬停展开的区块在指针离开后收起（掠过别的区块也不卡住）", async ({ page }) => {
  await page.goto("/#/about");
  const club = page.locator("section.about-block#block-club");
  const site = page.locator("section.about-block#block-site");

  // 悬停 280ms 后展开
  await club.locator(".about-block-head").hover();
  await expect(club).toHaveClass(/is-hover/);

  // 旧实现：指针从「关于我们」掠到「关于网站」再离开时，会清掉前一块的收起倒计时，
  // 「关于我们」就永远停在展开状态。这里同时断言两块都收起。
  await site.locator(".about-block-head").hover();
  await page.mouse.move(3, 3);

  await expect(club).not.toHaveClass(/is-hover/, { timeout: 3_000 });
  await expect(site).not.toHaveClass(/is-hover/, { timeout: 3_000 });
});

test("关于页：窗口失焦 / 指针移出窗口时收起悬停展开的区块", async ({ page }) => {
  await page.goto("/#/about");
  const club = page.locator("section.about-block#block-club");

  await club.locator(".about-block-head").hover();
  await expect(club).toHaveClass(/is-hover/);

  // 切换窗口 / 切到别的标签页时浏览器不会派发 mouseleave，需要主动收起
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(club).not.toHaveClass(/is-hover/, { timeout: 3_000 });

  // 再次悬停后，指针移出文档（relatedTarget 为空）也要收起。
  // 先把指针挪开：失焦收起时指针仍停在原处，再 hover 同一位置不会触发 mouseenter。
  await page.mouse.move(3, 3);
  await club.locator(".about-block-head").hover();
  await expect(club).toHaveClass(/is-hover/);
  await page.evaluate(() => {
    document.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: null }));
  });
  await expect(club).not.toHaveClass(/is-hover/, { timeout: 3_000 });
});
