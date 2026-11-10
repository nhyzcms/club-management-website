import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { claimMock } = vi.hoisted(() => ({ claimMock: vi.fn(() => Promise.resolve({})) }));

vi.mock("../../../api/client", () => ({ api: { memberClaim: claimMock } }));

import MemberClaimForm from "../MemberClaimForm";

const CANDIDATES = [
  { id: 11, name: "张三", cohort: 2 },
  { id: 12, name: "张三", cohort: 1 },
];

describe("MemberClaimForm（认领表单）", () => {
  it("选中身份 + 输入后四位后提交", async () => {
    const onDone = vi.fn();
    render(<MemberClaimForm candidates={CANDIDATES} onDone={onDone} />);
    fireEvent.click(screen.getAllByRole("radio")[1]);
    fireEvent.change(screen.getByLabelText("手机号后四位"), { target: { value: "9198" } });
    fireEvent.click(screen.getByRole("button", { name: "确认绑定" }));
    await waitFor(() => expect(claimMock).toHaveBeenCalledWith(12, "9198"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("失败时展示后端错误信息", async () => {
    claimMock.mockRejectedValueOnce(
      Object.assign(new Error("手机号后四位不匹配。"), { status: 400 }),
    );
    render(<MemberClaimForm candidates={CANDIDATES} onDone={() => {}} />);
    fireEvent.click(screen.getAllByRole("radio")[0]);
    fireEvent.change(screen.getByLabelText("手机号后四位"), { target: { value: "0000" } });
    fireEvent.click(screen.getByRole("button", { name: "确认绑定" }));
    expect(await screen.findByText("手机号后四位不匹配。")).toBeInTheDocument();
  });

  it("未选身份或后四位不足时按钮禁用", () => {
    render(<MemberClaimForm candidates={CANDIDATES} onDone={() => {}} />);
    const btn = screen.getByRole("button", { name: "确认绑定" });
    expect(btn).toBeDisabled();
    fireEvent.click(screen.getAllByRole("radio")[0]);
    expect(btn).toBeDisabled(); // 仍未输后四位
  });
});
