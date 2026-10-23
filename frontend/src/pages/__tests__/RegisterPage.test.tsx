import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { registerMock, memberIdentityMock } = vi.hoisted(() => ({
  registerMock: vi.fn(),
  memberIdentityMock: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  api: { register: registerMock, memberIdentity: memberIdentityMock },
}));
vi.mock("../../api/sitePolicy", () => ({
  useSitePolicy: () => ({ registration_enabled: true }),
}));
vi.mock("../../components/AppShell", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../../components/LoginModalProvider", () => ({
  useLoginModal: () => ({ openLogin: vi.fn(), notifyAuthChange: vi.fn() }),
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

import RegisterPage from "../RegisterPage";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/register"]}>
      <RegisterPage />
    </MemoryRouter>,
  );
}

describe("RegisterPage（注册页）· 校牌号", () => {
  it("只有在校生 / 毕业生显示校牌号输入框", () => {
    renderPage();
    expect(screen.queryByLabelText("校牌号")).not.toBeInTheDocument();

    const select = screen.getByLabelText("身份");
    fireEvent.change(select, { target: { value: "student" } });
    expect(screen.getByLabelText("校牌号")).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "graduate" } });
    expect(screen.getByLabelText("校牌号")).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "teacher" } });
    expect(screen.queryByLabelText("校牌号")).not.toBeInTheDocument();
  });

  it("填了校牌号则随注册表单提交", async () => {
    registerMock.mockResolvedValueOnce({ logged_in: true });
    memberIdentityMock.mockResolvedValueOnce({ enabled: true, bound: null, candidates: [] });

    renderPage();
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "newbie" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "StrongPass123!" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "StrongPass123!" } });
    fireEvent.change(screen.getByLabelText("真实姓名"), { target: { value: "张三" } });
    fireEvent.change(screen.getByLabelText("身份"), { target: { value: "student" } });
    fireEvent.change(screen.getByLabelText("校牌号"), { target: { value: " A001 " } });
    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    await waitFor(() => expect(registerMock).toHaveBeenCalledTimes(1));
    const fd = registerMock.mock.calls[0][0] as FormData;
    expect(fd.get("card_no")).toBe("A001");
    expect(fd.get("identity")).toBe("student");
  });
});
