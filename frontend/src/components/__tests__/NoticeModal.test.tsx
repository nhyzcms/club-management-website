import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import NoticeModal from "../NoticeModal";
import { EMAIL_DOMAIN_BLOCKED_MESSAGE } from "../../api/shared";

describe("NoticeModal", () => {
  it("渲染提示弹窗与文案（邮箱后缀白名单文案）", () => {
    render(<NoticeModal message={EMAIL_DOMAIN_BLOCKED_MESSAGE} onClose={() => {}} />);

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(EMAIL_DOMAIN_BLOCKED_MESSAGE)).toBeInTheDocument();
  });

  it("自定义标题与确认文案", () => {
    render(<NoticeModal title="邮箱不可用" message="x" confirmLabel="好" onClose={() => {}} />);

    expect(screen.getByText("邮箱不可用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "好" })).toBeInTheDocument();
  });

  it("确认按钮 / Esc 关闭", () => {
    const onClose = vi.fn();
    render(<NoticeModal message="x" onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "我知道了" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("点遮罩关闭，点卡片不关闭", () => {
    const onClose = vi.fn();
    render(<NoticeModal message="x" onClose={onClose} />);

    fireEvent.click(screen.getByText("x"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("alertdialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
