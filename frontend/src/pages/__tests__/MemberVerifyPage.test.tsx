import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const { checkMock } = vi.hoisted(() => ({ checkMock: vi.fn() }));

vi.mock("../../api/client", () => ({ api: { memberCheck: checkMock } }));
vi.mock("../../components/AppShell", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

import MemberVerifyPage from "../MemberVerifyPage";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/v/:code" element={<MemberVerifyPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("MemberVerifyPage（公开扫码校验页）", () => {
  it("校验通过时展示姓名 / 届数 / 组别 / 识别码", async () => {
    checkMock.mockResolvedValueOnce({
      found: true,
      name: "张三",
      cohort: 2,
      code: "26020001",
      status: "active",
      avatar: null,
    });
    renderAt("/v/26020001?s=sig123");
    expect(await screen.findByText("张三")).toBeInTheDocument();
    expect(screen.getByText("第 2 届")).toBeInTheDocument();
    expect(screen.getByText("识别码 26020001")).toBeInTheDocument();
    expect(checkMock).toHaveBeenCalledWith("26020001", "sig123");
  });

  it("404（码不存在 / 签名不符）时展示无效提示", async () => {
    checkMock.mockRejectedValueOnce(
      Object.assign(new Error("请求的资源不存在。"), { status: 404 }),
    );
    renderAt("/v/99999999?s=dead");
    expect(await screen.findByText(/未找到匹配的社员身份/)).toBeInTheDocument();
  });
});
