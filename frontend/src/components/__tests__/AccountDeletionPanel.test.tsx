import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import AccountDeletionPanel from "../profile/AccountDeletionPanel";

vi.mock("../../api/client", () => ({
  api: { deleteAccount: vi.fn() },
}));

describe("AccountDeletionPanel", () => {
  it("三重确认齐全才允许提交", () => {
    render(<AccountDeletionPanel />);
    const submit = screen.getByRole("button", { name: "永久注销账号" });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "StrongPass123!" } });
    fireEvent.change(screen.getByLabelText(/输入「注销账号」以确认/), {
      target: { value: "注销账号" },
    });
    expect(submit).toBeDisabled(); // 还没勾选

    fireEvent.click(screen.getByRole("checkbox"));
    expect(submit).not.toBeDisabled();
  });

  it("确认短语必须逐字一致", () => {
    render(<AccountDeletionPanel />);
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("checkbox"));

    fireEvent.change(screen.getByLabelText(/输入「注销账号」以确认/), {
      target: { value: "注销" },
    });
    expect(screen.getByRole("button", { name: "永久注销账号" })).toBeDisabled();
  });
});
