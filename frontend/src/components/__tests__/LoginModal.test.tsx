/**
 * 登录弹窗：拖选内容不能把弹窗关掉（#180）。
 *
 * 浏览器对「按下与抬起落在不同元素」的点击，会把 click 派发到两者的**最近共同
 * 祖先**。拖选密码时鼠标移出卡片、在遮罩上松开，click 的 target 就是遮罩——
 * 旧写法 `onClick={handleDismiss}` 会直接关掉弹窗，用户正在输密码就被踢回首页。
 *
 * 这些用例按同样的顺序模拟：先 mousedown 在输入框、再 click 在遮罩上。
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../api/client", () => ({
  api: { login: vi.fn(), loginWithEmail: vi.fn() },
}));
vi.mock("../../api/sitePolicy", () => ({
  useSitePolicy: () => ({ registration_enabled: true }),
}));
vi.mock("../../turnstile", () => ({
  useTurnstile: () => ({
    containerRef: { current: null },
    token: "",
    reset: vi.fn(),
    enabled: false,
    policyReady: true,
  }),
}));

import LoginModal from "../LoginModal";

function setup(onClose = vi.fn()) {
  const utils = render(
    <MemoryRouter>
      <LoginModal open onClose={onClose} />
    </MemoryRouter>,
  );
  const scrim = document.querySelector(".modal-scrim") as HTMLElement;
  const password = document.querySelector("#auth-password") as HTMLInputElement;
  return { ...utils, onClose, scrim, password };
}

describe("LoginModal 遮罩关闭", () => {
  it("拖选密码时鼠标在遮罩上松开，不关闭弹窗", () => {
    const { onClose, scrim, password } = setup();

    // 按下发生在输入框里……（模拟拖动选择）
    fireEvent.mouseDown(password);
    // ……抬起发生在遮罩上，浏览器把 click 派发到共同祖先（遮罩）
    fireEvent.click(scrim);

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("真正点击遮罩仍然关闭", () => {
    const { onClose, scrim } = setup();

    fireEvent.mouseDown(scrim);
    fireEvent.click(scrim);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("从卡片内按下、遮罩上抬起（反向拖动）同样不关闭", () => {
    const { onClose, scrim } = setup();
    const card = document.querySelector(".modal") as HTMLElement;

    fireEvent.mouseDown(card);
    fireEvent.click(scrim);

    expect(onClose).not.toHaveBeenCalled();
  });

  it("点关闭按钮照常关闭", () => {
    const { onClose } = setup();

    fireEvent.click(screen.getByLabelText("关闭"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Esc 照常关闭", () => {
    const { onClose } = setup();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
