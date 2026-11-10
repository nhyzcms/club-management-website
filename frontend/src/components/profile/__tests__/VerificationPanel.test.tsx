import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const { statusMock, validityMock } = vi.hoisted(() => ({
  statusMock: vi.fn(),
  validityMock: vi.fn(),
}));

vi.mock("../../../api/client", () => ({
  api: {
    verificationStatus: statusMock,
    accountValidity: validityMock,
    verificationEmailBind: vi.fn(),
    verificationManualSubmit: vi.fn(),
    verificationAuthcodeRedeem: vi.fn(),
  },
}));

import VerificationPanel from "../VerificationPanel";

function card(channel: string, status: string, identifier = "") {
  return {
    channel,
    status,
    identifier,
    verified_at: status === "approved" ? "2026-10-24T10:00:00+08:00" : null,
  };
}

describe("VerificationPanel（认证方式单一化）", () => {
  beforeEach(() => {
    validityMock.mockRejectedValue(new Error("unused in this test"));
  });

  it("已通过人工审批：其余通道显示「无需再次认证」并收掉表单", async () => {
    statusMock.mockResolvedValueOnce({
      is_verified: true,
      channels: [
        card("appointment", "not_required"),
        card("email", "not_required"),
        card("manual", "approved"),
        card("authcode", "not_required"),
      ],
    });
    render(<VerificationPanel />);

    expect(await screen.findByText(/你的账号已通过「人工审批」完成认证/)).toBeInTheDocument();
    // 委任卡在 not_required 时不铺卡 → 只剩邮箱 / 认证码两张「无需再次认证」
    expect(screen.getAllByText("无需再次认证")).toHaveLength(2);
    expect(screen.getByText("已通过")).toBeInTheDocument(); // 手动通道仍是 approved
    expect(screen.queryByRole("button", { name: "提交身份证明" })).toBeNull();
    expect(screen.queryByPlaceholderText("输入认证码")).toBeNull();
  });

  it("已认证但未绑邮箱：仍保留折叠的绑定入口（仅用于登录 / 找回密码）", async () => {
    statusMock.mockResolvedValueOnce({
      is_verified: true,
      channels: [
        card("appointment", "not_required"),
        card("email", "not_required"),
        card("manual", "approved"),
        card("authcode", "not_required"),
      ],
    });
    render(<VerificationPanel />);

    const bindButton = await screen.findByRole("button", {
      name: "绑定邮箱（仅用于登录 / 找回密码）",
    });
    expect(screen.queryByPlaceholderText("email@example.com")).toBeNull();
    fireEvent.click(bindButton);
    expect(await screen.findByPlaceholderText("email@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "绑定邮箱" })).toBeInTheDocument();
  });

  it("未认证：不出现「无需再次认证」，各通道表单照常可用", async () => {
    statusMock.mockResolvedValueOnce({
      is_verified: false,
      channels: [
        card("appointment", "none"),
        card("email", "none"),
        card("manual", "none"),
        card("authcode", "none"),
      ],
    });
    render(<VerificationPanel />);

    expect(await screen.findByText(/你的账号尚未认证/)).toBeInTheDocument();
    expect(screen.queryByText("无需再次认证")).toBeNull();
    expect(screen.getByRole("button", { name: "提交身份证明" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("输入认证码")).toBeInTheDocument();
  });
});
