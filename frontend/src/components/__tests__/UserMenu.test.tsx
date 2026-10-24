import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import UserMenu, { type UserMenuProps } from "../UserMenu";

function setup(overrides: Partial<UserMenuProps> = {}) {
  const props: UserMenuProps = {
    user: { id: 1, username: "e2e_info" },
    profile: { nickname: "E2E 信息员", avatar: null },
    verified: true,
    dmsEnabled: true,
    canReview: true,
    showAdmin: true,
    themePref: "light",
    onThemeSelect: vi.fn(),
    onNavigate: vi.fn(),
    onLogout: vi.fn(),
    ...overrides,
  };
  render(<UserMenu {...props} />);
  const trigger = screen.getByRole("button", { name: "打开用户菜单" });
  return { trigger, props };
}

async function openMenu(trigger: HTMLElement) {
  fireEvent.click(trigger);
  const menu = screen.getByRole("menu", { name: "用户菜单" });
  const first = screen.getByRole("menuitem", { name: "个人中心" });
  await waitFor(() => expect(first).toHaveFocus());
  return { menu, first };
}

describe("UserMenu（GitHub 式头像菜单）", () => {
  it("触发器为纯头像按钮并带菜单语义", () => {
    const { trigger } = setup();

    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveAttribute("aria-controls", "user-menu-list");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("点击打开：渲染菜单、aria-expanded=true、焦点进入第一项（roving tabindex）", async () => {
    const { trigger } = setup();
    const { first } = await openMenu(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(first).toHaveFocus();
    expect(first).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("menuitem", { name: "通知" })).toHaveAttribute("tabindex", "-1");
  });

  it("触发器按 ArrowDown 打开并聚焦第一项", async () => {
    const { trigger } = setup();

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "个人中心" })).toHaveFocus());
  });

  it("↑↓ 键在条目间循环移动", async () => {
    const { trigger } = setup();
    const { menu } = await openMenu(trigger);

    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "私信" })).toHaveFocus();

    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(screen.getByRole("menuitem", { name: "个人中心" })).toHaveFocus();

    // 从第一项继续向上 → 循环到末项「退出登录」
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(screen.getByRole("menuitem", { name: "退出登录" })).toHaveFocus();

    // 从末项继续向下 → 循环回第一项
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "个人中心" })).toHaveFocus();
  });

  it("Escape 关闭菜单并把焦点还给触发器", async () => {
    const { trigger } = setup();
    const { menu } = await openMenu(trigger);

    fireEvent.keyDown(menu, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("点击条目：执行导航回调并关闭菜单", async () => {
    const { trigger, props } = setup();
    await openMenu(trigger);

    fireEvent.click(screen.getByRole("menuitem", { name: "个人中心" }));

    expect(props.onNavigate).toHaveBeenCalledWith("/profile");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("外观单选：回调生效、菜单保持打开、aria-checked 标记当前项", async () => {
    const { trigger, props } = setup({ themePref: "light" });
    await openMenu(trigger);

    const light = screen.getByRole("menuitemradio", { name: "浅色模式" });
    const dark = screen.getByRole("menuitemradio", { name: "深色模式" });
    expect(light).toHaveAttribute("aria-checked", "true");
    expect(dark).toHaveAttribute("aria-checked", "false");

    fireEvent.click(dark);
    expect(props.onThemeSelect).toHaveBeenCalledWith("dark");
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("点外部关闭、点菜单内部不关闭", async () => {
    const { trigger } = setup();
    const { menu } = await openMenu(trigger);

    fireEvent.mouseDown(menu);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("条件项：未认证 / 私信开关 / 审核权限正确裁剪菜单", async () => {
    setup({ verified: false, dmsEnabled: false, canReview: false });
    fireEvent.click(screen.getByRole("button", { name: "打开用户菜单" }));

    expect(screen.queryByRole("menuitem", { name: "私信" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "待办" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "审核队列" })).not.toBeInTheDocument();
    // 未认证时内容组仍有「个人中心 / 通知」
    expect(screen.getByRole("menuitem", { name: "通知" })).toBeInTheDocument();
  });

  it("无后台权限时隐藏「后台管理」（普通用户 / 访客）", async () => {
    const { trigger } = setup({ showAdmin: false });
    await openMenu(trigger);

    expect(screen.queryByRole("menuitem", { name: "后台管理" })).not.toBeInTheDocument();
    // 其它条目不受影响
    expect(screen.getByRole("menuitem", { name: "个人中心" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "通知" })).toBeInTheDocument();
  });

  it("有后台权限时显示「后台管理」并跳转 /admin/", async () => {
    const { trigger, props } = setup({ showAdmin: true });
    await openMenu(trigger);

    fireEvent.click(screen.getByRole("menuitem", { name: "后台管理" }));
    expect(props.onNavigate).toHaveBeenCalledWith("/admin/");
  });
});
