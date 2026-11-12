import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfileCompletionModal from "../ProfileCompletionModal";
import ProfileCompletionHost, { missingProfileFields } from "../ProfileCompletionHost";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: { me: vi.fn() } }));

vi.mock("../LoginModalProvider", () => ({
  useLoginModal: () => ({ authNonce: 0 }),
}));

const DISMISS_KEY = "nhyz.profilePrompt.dismissed";

function snapshot(profile: Record<string, unknown>) {
  return { user: { id: 42, username: "stu", email: "" }, profile };
}

function renderHost(entry = "/") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ProfileCompletionHost />
    </MemoryRouter>,
  );
}

describe("ProfileCompletionModal", () => {
  it("列出缺项，两个按钮各自回调", () => {
    const onLater = vi.fn();
    const onFill = vi.fn();
    render(<ProfileCompletionModal missing={["真实姓名", "校牌号"]} onLater={onLater} onFill={onFill} />);

    const dialog = screen.getByRole("alertdialog", { name: "完善实名资料" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("真实姓名")).toBeInTheDocument();
    expect(screen.getByText("校牌号")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下次一定" }));
    expect(onLater).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "立即填写" }));
    expect(onFill).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 等同「下次一定」", () => {
    const onLater = vi.fn();
    render(<ProfileCompletionModal missing={["真实姓名"]} onLater={onLater} onFill={() => {}} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onLater).toHaveBeenCalledTimes(1);
  });
});

describe("missingProfileFields", () => {
  it("真实姓名与可补录的校牌号都空 → 两项都提醒", () => {
    expect(
      missingProfileFields({ real_name: "", identity: "student", card_no: "", card_no_editable: true }),
    ).toEqual(["真实姓名", "校牌号"]);
  });

  it("教师 / 家长不登记校牌号 → 只提醒真实姓名", () => {
    expect(
      missingProfileFields({ real_name: "  ", identity: "teacher", card_no: "", card_no_editable: false }),
    ).toEqual(["真实姓名"]);
  });

  it("校牌号由名册决定（不可补录）时不提醒，避免改不了的死循环", () => {
    expect(
      missingProfileFields({ real_name: "张三", identity: "student", card_no: "", card_no_editable: false }),
    ).toEqual([]);
  });

  it("资料齐全 → 不提醒", () => {
    expect(
      missingProfileFields({ real_name: "张三", identity: "student", card_no: "A123", card_no_editable: false }),
    ).toEqual([]);
  });
});

describe("ProfileCompletionHost", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("登录后资料缺项 → 弹窗；「下次一定」后本次会话不再弹", async () => {
    (api.me as any).mockResolvedValue(
      snapshot({ real_name: "", identity: "student", card_no: "", card_no_editable: true }),
    );

    const first = renderHost();
    expect(await screen.findByRole("alertdialog", { name: "完善实名资料" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下次一定" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(sessionStorage.getItem(DISMISS_KEY)).toBe("1");

    // 同一登录会话内刷新 / 重新挂载：不再打扰。
    first.unmount();
    renderHost();
    await waitFor(() => expect(api.me).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("登出（me 失败）会清掉「下次一定」标记，下次登录照弹", async () => {
    sessionStorage.setItem(DISMISS_KEY, "1");
    (api.me as any).mockRejectedValue(new Error("401"));
    renderHost();

    await waitFor(() => expect(sessionStorage.getItem(DISMISS_KEY)).toBeNull());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("已经站在本人资料编辑页时不弹（弹了也是盖住表单）", async () => {
    (api.me as any).mockResolvedValue(
      snapshot({ real_name: "", identity: "student", card_no: "", card_no_editable: true }),
    );
    renderHost("/u/42?tab=profile");

    await waitFor(() => expect(api.me).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    // 标记没被写：说明只是「这一页不弹」，不是被当成已跳过。
    expect(sessionStorage.getItem(DISMISS_KEY)).toBeNull();
  });

  it("资料齐全时不弹，并清掉遗留标记", async () => {
    sessionStorage.setItem(DISMISS_KEY, "1");
    (api.me as any).mockResolvedValue(
      snapshot({ real_name: "张三", identity: "student", card_no: "A123", card_no_editable: false }),
    );
    renderHost();

    await waitFor(() => expect(api.me).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(DISMISS_KEY)).toBeNull();
  });
});
