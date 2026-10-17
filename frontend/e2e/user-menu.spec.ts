import { test, expect } from "@playwright/test";

// 顶栏头像菜单（GitHub 式）：打开 / 键盘导航 / 焦点管理 / 外部与失焦关闭
test("头像菜单：点击打开、方向键导航、Esc 归还焦点、点外部关闭", async ({ page }) => {
  await page.goto("/");

  const trigger = page.getByRole("button", { name: "打开用户菜单" });
  await expect(trigger).toBeVisible({ timeout: 10_000 });
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await trigger.click();
  const menu = page.getByRole("menu", { name: "用户菜单" });
  await expect(menu).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");

  // 打开即聚焦第一项；↓ 移动到第二项（roving tabindex）
  await expect(menu.getByRole("menuitem").first()).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem").nth(1)).toBeFocused();

  // Esc：关闭 + 焦点回到触发器
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  // 点外部关闭（顶栏 Logo，仍在首页）
  await trigger.click();
  await expect(menu).toBeVisible();
  await page.getByRole("banner").getByRole("button", { name: "传媒社 首页" }).click();
  await expect(menu).toBeHidden();
});

test("头像菜单：Tab 焦点离开时自动关闭", async ({ page }) => {
  await page.goto("/");

  const trigger = page.getByRole("button", { name: "打开用户菜单" });
  await trigger.click();
  const menu = page.getByRole("menu", { name: "用户菜单" });
  await expect(menu).toBeVisible();

  await page.keyboard.press("Tab");
  await expect(menu).toBeHidden();
});
