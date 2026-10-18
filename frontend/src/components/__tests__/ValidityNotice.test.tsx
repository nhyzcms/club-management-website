import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ValidityNoticeModal from "../ValidityNoticeModal";
import ValidityNoticeHost from "../ValidityNoticeHost";
import type { ValiditySummary } from "../../utils/validity";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { accountValidity: vi.fn(), accountValidityAck: vi.fn() },
}));

vi.mock("../LoginModalProvider", () => ({
  useLoginModal: () => ({ authNonce: 0 }),
}));

function summary(overrides: Partial<ValiditySummary> = {}): ValiditySummary {
  const expiresAt = new Date(Date.now() + 60 * 86400_000).toISOString();
  return {
    status: "unverified",
    status_label: "未认证用户",
    expires_at: expiresAt,
    remaining_days: 60,
    registration_deadline: expiresAt,
    channels: [],
    policy: {
      verification_valid_days: 365,
      admin_valid_days: 730,
      registration_verify_days: 60,
    },
    key: "unverified:" + expiresAt,
    notice_pending: true,
    ...overrides,
  };
}

describe("ValidityNoticeModal", () => {
  it("未认证用户显示认证截止、剩余天数与三条规则", () => {
    render(<ValidityNoticeModal data={summary()} onClose={() => {}} />);

    expect(screen.getByRole("alertdialog", { name: "账号有效期" })).toBeInTheDocument();
    expect(screen.getByText("认证截止时间")).toBeInTheDocument();
    expect(screen.getByText("60 天")).toBeInTheDocument();
    expect(screen.getByText(/认证有效期 365 天/)).toBeInTheDocument();
    expect(screen.getByText(/管理员委任有效期 730 天/)).toBeInTheDocument();
    expect(screen.getByText(/注册宽限 60 天/)).toBeInTheDocument();
  });

  it("已认证用户显示账号到期时间与身份", () => {
    render(
      <ValidityNoticeModal
        data={summary({ status: "verified", status_label: "已认证用户", remaining_days: 365 })}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText("账号到期时间")).toBeInTheDocument();
    expect(screen.getByText("已认证用户")).toBeInTheDocument();
    expect(screen.getByText("365 天")).toBeInTheDocument();
  });

  it("超级管理员显示永久有效", () => {
    render(
      <ValidityNoticeModal
        data={summary({
          status: "permanent",
          status_label: "超级管理员（永久有效）",
          expires_at: null,
          remaining_days: null,
          registration_deadline: null,
        })}
        onClose={() => {}}
      />,
    );

    expect(screen.getAllByText("永久有效").length).toBeGreaterThan(0);
  });

  it("点「我知道了」关闭", () => {
    const onClose = vi.fn();
    render(<ValidityNoticeModal data={summary()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "我知道了" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ValidityNoticeHost", () => {
  beforeEach(() => {
    (api.accountValidity as any).mockReset();
    (api.accountValidityAck as any).mockReset();
    (api.accountValidityAck as any).mockResolvedValue({ acknowledged: true });
  });

  it("待提示时自动弹窗，关闭时把当前键写回服务端", async () => {
    const data = summary();
    (api.accountValidity as any).mockResolvedValue(data);

    render(<ValidityNoticeHost />);

    const dialog = await screen.findByRole("alertdialog", { name: "账号有效期" });
    expect(dialog).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "我知道了" }));
    await waitFor(() =>
      expect(api.accountValidityAck).toHaveBeenCalledWith(data.key),
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("没有待提示时不渲染弹窗", async () => {
    (api.accountValidity as any).mockResolvedValue(summary({ notice_pending: false }));

    render(<ValidityNoticeHost />);
    await waitFor(() => expect(api.accountValidity).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
