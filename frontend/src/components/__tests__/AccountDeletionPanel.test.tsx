import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AccountDeletionPanel from "../profile/AccountDeletionPanel";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { deleteAccount: vi.fn() },
}));

function fillValidForm() {
  fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "StrongPass123!" } });
  fireEvent.change(screen.getByLabelText(/输入「注销账号」以确认/), {
    target: { value: "注销账号" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
}

describe("AccountDeletionPanel", () => {
  beforeEach(() => {
    (api.deleteAccount as any).mockReset();
    // 不 resolve：避免成功后 window.location.replace 在 jsdom 里报「未实现」。
    (api.deleteAccount as any).mockReturnValue(new Promise(() => {}));
  });

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

  it("填对后先弹二次确认，取消不调用接口", () => {
    render(<AccountDeletionPanel />);
    fillValidForm();

    fireEvent.click(screen.getByRole("button", { name: "永久注销账号" }));
    expect(screen.getByRole("alertdialog", { name: "确认永久注销账号？" })).toBeInTheDocument();
    expect(api.deleteAccount).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "再想想" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.deleteAccount).not.toHaveBeenCalled();
  });

  it("弹窗内确认后才调用注销接口", async () => {
    render(<AccountDeletionPanel />);
    fillValidForm();

    fireEvent.click(screen.getByRole("button", { name: "永久注销账号" }));
    fireEvent.click(screen.getByRole("button", { name: "确认注销" }));

    await waitFor(() => expect(api.deleteAccount).toHaveBeenCalledTimes(1));
    expect(api.deleteAccount).toHaveBeenCalledWith("StrongPass123!", expect.anything());
  });
});
