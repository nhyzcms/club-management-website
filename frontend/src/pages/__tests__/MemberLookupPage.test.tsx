import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { lookupMock } = vi.hoisted(() => ({ lookupMock: vi.fn() }));

vi.mock("../../api/client", () => ({ api: { memberLookup: lookupMock } }));
vi.mock("../../components/AppShell", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

import MemberLookupPage from "../MemberLookupPage";

const QUOTA = { limit: 3, used: 0, remaining: 3, reset_at: null, window_hours: 24 };

function renderPage(entry = "/v") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <MemberLookupPage />
    </MemoryRouter>,
  );
}

function submitWith(value: string) {
  fireEvent.change(screen.getByLabelText("或手动输入编号"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "查询" }));
}

describe("MemberLookupPage（编号查询入口）", () => {
  it("12 位条码载荷命中时用公共结果卡展示", async () => {
    lookupMock.mockResolvedValueOnce({
      found: true,
      results: [{ name: "谢二", cohort: 9, code: "26090188", status: "active", avatar: null }],
      quota: QUOTA,
    });
    renderPage();
    submitWith("260901667878");

    expect(await screen.findByText("谢二")).toBeInTheDocument();
    expect(screen.getByText("第 9 届")).toBeInTheDocument();
    expect(screen.getByText("识别码 26090188")).toBeInTheDocument();
    expect(lookupMock).toHaveBeenCalledWith("260901667878");
  });

  it("未命中时提示未找到，并给出剩余额度", async () => {
    lookupMock.mockResolvedValueOnce({
      found: false,
      results: [],
      quota: { ...QUOTA, used: 1, remaining: 2 },
    });
    renderPage();
    submitWith("260901000000");

    expect(await screen.findByText(/未找到匹配的社员身份/)).toBeInTheDocument();
    expect(screen.getByText(/今日还可查 2 次/)).toBeInTheDocument();
  });

  it("额度用尽（429）时展示服务端文案", async () => {
    lookupMock.mockRejectedValueOnce(
      Object.assign(new Error("查询次数已达上限（每 24 小时最多 3 次），请稍后再试。"), {
        status: 429,
      }),
    );
    renderPage();
    submitWith("26090188");

    expect(await screen.findByText(/查询次数已达上限/)).toBeInTheDocument();
  });

  it("深链接 ?q= 自动查一次（App 原生扫码落地用）", async () => {
    lookupMock.mockResolvedValueOnce({
      found: true,
      results: [{ name: "谢二", cohort: 9, code: "26090188", status: "active", avatar: null }],
      quota: QUOTA,
    });
    renderPage("/v?q=260901667878");

    expect(await screen.findByText("谢二")).toBeInTheDocument();
    // 只查一次：12 位条码签名即证明，重复查会白扣额度
    expect(lookupMock).toHaveBeenCalledTimes(1);
    expect(lookupMock).toHaveBeenCalledWith("260901667878");
    expect((screen.getByLabelText("或手动输入编号") as HTMLInputElement).value).toBe("260901667878");
  });

  it("输入为空时查询按钮禁用", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "查询" })).toBeDisabled();
  });
});
