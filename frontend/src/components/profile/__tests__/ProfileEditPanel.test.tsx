import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProfileEditPanel from "../ProfileEditPanel";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({
  api: { getProfile: vi.fn(), updateProfile: vi.fn() },
}));

function profile(overrides: Record<string, unknown> = {}) {
  return {
    avatar: null,
    nickname: "",
    birthday: null,
    gender: "",
    bio: "",
    real_name: "",
    real_name_editable: true,
    real_name_locked_until: null,
    identity: "student",
    card_no: "",
    card_no_editable: true,
    card_no_locked_reason: "",
    ...overrides,
  };
}

describe("ProfileEditPanel 实名资料", () => {
  beforeEach(() => {
    (api.getProfile as any).mockReset();
    (api.updateProfile as any).mockReset();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("已登记姓名与已绑定校牌号都置灰，并给出解锁 / 更正提示", async () => {
    (api.getProfile as any).mockResolvedValue({
      profile: profile({
        real_name: "张三",
        real_name_editable: false,
        real_name_locked_until: "2027-01-01T00:00:00+08:00",
        card_no: "2601001",
        card_no_editable: false,
        card_no_locked_reason: "member",
      }),
    });

    render(<ProfileEditPanel onSaved={() => {}} />);
    const name = await screen.findByLabelText("真实姓名");
    const card = screen.getByLabelText("校牌号");
    expect(name).toBeDisabled();
    expect(card).toBeDisabled();
    expect(screen.getByText(/后可自行修改/)).toBeInTheDocument();
    expect(screen.getByText(/以社员名册为准/)).toBeInTheDocument();
  });

  it("空姓名 / 校牌号可补录，提交后立即锁定", async () => {
    (api.getProfile as any).mockResolvedValue({ profile: profile() });
    (api.updateProfile as any).mockResolvedValue({
      profile: profile({
        real_name: "李四",
        real_name_editable: false,
        card_no: "2601002",
        card_no_editable: false,
        card_no_locked_reason: "member",
      }),
    });

    render(<ProfileEditPanel onSaved={() => {}} />);
    const name = await screen.findByLabelText("真实姓名");
    const card = screen.getByLabelText("校牌号");
    expect(name).not.toBeDisabled();
    expect(card).not.toBeDisabled();

    fireEvent.change(name, { target: { value: "李四" } });
    fireEvent.change(card, { target: { value: "2601002" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(api.updateProfile).toHaveBeenCalledTimes(1));
    const fd = (api.updateProfile as any).mock.calls[0][0] as FormData;
    expect(fd.get("real_name")).toBe("李四");
    expect(fd.get("card_no")).toBe("2601002");
    await waitFor(() => expect(screen.getByLabelText("真实姓名")).toBeDisabled());
    expect(screen.getByLabelText("校牌号")).toBeDisabled();
  });

  it("教师身份不显示校牌号", async () => {
    (api.getProfile as any).mockResolvedValue({ profile: profile({ identity: "teacher" }) });
    render(<ProfileEditPanel onSaved={() => {}} />);
    await screen.findByLabelText("真实姓名");
    expect(screen.queryByLabelText("校牌号")).not.toBeInTheDocument();
  });
});
