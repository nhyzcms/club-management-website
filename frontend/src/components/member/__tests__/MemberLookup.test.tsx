import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { quotaMock, lookupMock } = vi.hoisted(() => ({
  quotaMock: vi.fn(),
  lookupMock: vi.fn(),
}));

vi.mock("../../../api/client", () => ({
  api: { memberLookupQuota: quotaMock, memberLookup: lookupMock },
}));

import MemberLookup from "../MemberLookup";

const quota = (limit: number | null, used = 0, remaining: number | null = null) => ({
  quota: { limit, used, remaining, reset_at: null, window_hours: 24 },
});

function search(value: string) {
  fireEvent.change(screen.getByLabelText("社员查询"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: /查询/ }));
}

describe("MemberLookup（首页社员查询）", () => {
  it("展示剩余额度", async () => {
    quotaMock.mockResolvedValue(quota(3, 1, 2));
    render(<MemberLookup />);
    expect(await screen.findByText(/今日还可查 2 次/)).toBeInTheDocument();
  });

  it("按姓名查询后弹窗展示与扫码页一致的结果卡", async () => {
    quotaMock.mockResolvedValue(quota(3, 0, 3));
    lookupMock.mockResolvedValue({
      found: true,
      results: [{ name: "张三", cohort: 1, code: "26010201", status: "active", avatar: null }],
      quota: { limit: 3, used: 1, remaining: 2, reset_at: null, window_hours: 24 },
    });
    render(<MemberLookup />);
    search("张三");

    expect(await screen.findByText("张三")).toBeInTheDocument();
    expect(screen.getByText("第 1 届")).toBeInTheDocument();
    expect(screen.getByText("识别码 26010201")).toBeInTheDocument();
    expect(screen.getByText("本页来自社员查询，仅展示公开信息。")).toBeInTheDocument();
    expect(lookupMock).toHaveBeenCalledWith("张三");
  });

  it("查无此人时提示未找到", async () => {
    quotaMock.mockResolvedValue(quota(3, 0, 3));
    lookupMock.mockResolvedValue({
      found: false,
      results: [],
      quota: { limit: 3, used: 1, remaining: 2, reset_at: null, window_hours: 24 },
    });
    render(<MemberLookup />);
    search("查无此人");
    expect(await screen.findByText(/未找到匹配的社员/)).toBeInTheDocument();
  });

  it("额度用尽时展示服务端原因", async () => {
    quotaMock.mockResolvedValue(quota(3, 3, 0));
    lookupMock.mockRejectedValue(new Error("查询次数已达上限（每 24 小时最多 3 次），请稍后再试。"));
    render(<MemberLookup />);
    search("张三");
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("查询次数已达上限"),
    );
  });
});
