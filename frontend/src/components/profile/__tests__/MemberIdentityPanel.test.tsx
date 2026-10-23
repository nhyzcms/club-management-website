import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const { identityMock } = vi.hoisted(() => ({ identityMock: vi.fn() }));

vi.mock("../../../api/client", () => ({
  api: { memberIdentity: identityMock, memberClaim: vi.fn() },
}));

import MemberIdentityPanel from "../MemberIdentityPanel";

describe("MemberIdentityPanel（社员身份面板）", () => {
  it("已绑定：展示识别码与届数组别", async () => {
    identityMock.mockResolvedValueOnce({
      enabled: true,
      bound: {
        id: 1,
        name: "张三",
        cohort: 2,
        group: "摄影",
        code: "26020001",
        card_no: "A001",
        status: "active",
        bound_at: null,
      },
      candidates: [],
    });
    render(<MemberIdentityPanel />);
    expect(await screen.findByText("26020001")).toBeInTheDocument();
    expect(screen.getByText("第 2 届 · 摄影")).toBeInTheDocument();
    expect(screen.getByText("校牌号 A001")).toBeInTheDocument();
  });

  it("未绑定且有候选：渲染认领引导与表单", async () => {
    identityMock.mockResolvedValueOnce({
      enabled: true,
      bound: null,
      candidates: [{ id: 11, name: "张三", cohort: 2, group: "摄影" }],
    });
    render(<MemberIdentityPanel />);
    expect(
      await screen.findByText("以下身份是否是你？选择一条并输入手机号后四位完成绑定。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认绑定" })).toBeInTheDocument();
  });

  it("未绑定且无候选：给出说明文案", async () => {
    identityMock.mockResolvedValueOnce({ enabled: true, bound: null, candidates: [] });
    render(<MemberIdentityPanel />);
    expect(await screen.findByText(/暂无可认领的身份/)).toBeInTheDocument();
  });
});
