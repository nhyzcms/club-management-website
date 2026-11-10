import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import CommentThreadStatusField from "../CommentThreadStatusField";

describe("CommentThreadStatusField", () => {
  it("渲染三个选项并标记当前值", () => {
    render(<CommentThreadStatusField value="muted" onChange={() => {}} />);

    expect(screen.getByRole("radiogroup", { name: "评论区状态" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开放" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("button", { name: "评论区禁言" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "彻底关闭" })).toHaveAttribute("aria-selected", "false");
  });

  it("点击选项回调对应状态", () => {
    const onChange = vi.fn();
    render(<CommentThreadStatusField value="open" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "彻底关闭" }));
    expect(onChange).toHaveBeenCalledWith("closed");
  });

  it("disabled 时按钮不可用", () => {
    render(<CommentThreadStatusField value="open" onChange={() => {}} disabled />);
    expect(screen.getByRole("button", { name: "开放" })).toBeDisabled();
  });
});
