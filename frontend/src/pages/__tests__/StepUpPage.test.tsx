import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const { statusMock, verifyMock, questionsMock, storeGrantMock } = vi.hoisted(() => ({
  statusMock: vi.fn(),
  verifyMock: vi.fn(() => Promise.resolve({ grant: "g1", expires_in: 600, message: "ok" })),
  questionsMock: vi.fn(() => Promise.resolve({ bank: [], mine: [] })),
  storeGrantMock: vi.fn(),
}));

vi.mock("../../api/stepup", () => ({
  STEPUP_SCOPE_LABELS: { change_password: "修改密码" },
  stepupApi: { status: statusMock, emailSend: vi.fn(), verify: verifyMock, questions: questionsMock },
  storeGrant: storeGrantMock,
}));
vi.mock("../../components/AppShell", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../../components/LoginModalProvider", () => {
  // openLogin 必须是稳定引用：每次渲染新建会让 useEffect(loadStatus, [openLogin]) 反复重跑。
  const openLogin = vi.fn();
  return { useLoginModal: () => ({ openLogin }) };
});

import StepUpPage from "../StepUpPage";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/verify" element={<StepUpPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("StepUpPage（安全验证页）", () => {
  it("邮箱可用：输入验证码 → 验证并保存 grant", async () => {
    statusMock.mockResolvedValueOnce({
      scopes: { change_password: "修改密码" },
      email: { available: true, address: "u***@x.com", cooldown_remaining: 0 },
      questions: { configured: false, count: 0 },
      grant_ttl: 600,
    });
    renderAt("/verify?action=change_password&next=/profile");
    expect(await screen.findByText(/正在为「修改密码」完成本人确认/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("验证码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "完成验证并继续" }));
    await waitFor(() =>
      expect(verifyMock).toHaveBeenCalledWith({ method: "email", scope: "change_password", code: "123456" }),
    );
    await waitFor(() => expect(storeGrantMock).toHaveBeenCalledWith("change_password", "g1"));
  });

  it("无邮箱且未设问题：给出设置引导", async () => {
    statusMock.mockResolvedValueOnce({
      scopes: {},
      email: { available: false, address: "", cooldown_remaining: 0 },
      questions: { configured: false, count: 0 },
      grant_ttl: 600,
    });
    renderAt("/verify?action=change_email");
    expect(await screen.findByText(/尚未设置安全问题/)).toBeInTheDocument();
  });

  it("无 action：管理入口文案", async () => {
    statusMock.mockResolvedValueOnce({
      scopes: {},
      email: { available: true, address: "u***@x.com", cooldown_remaining: 0 },
      questions: { configured: true, count: 2 },
      grant_ttl: 600,
    });
    renderAt("/verify");
    expect(
      await screen.findByText(/从「修改密码 \/ 换绑邮箱」等操作进入时会自动带入目标/),
    ).toBeInTheDocument();
  });
});
