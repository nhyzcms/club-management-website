import { describe, expect, it } from "vitest";
import { deskTabs } from "../reviewDesk";

/**
 * 审核台的「桌」清单是桌面 / 手机两套 UI 的共同契约：
 * 顺序与可见性一旦漂移，手机版就会出现「桌面能审、手机看不到」的分裂。
 */
describe("reviewDesk.deskTabs", () => {
  it("没有任何审核能力时返回空数组", () => {
    expect(deskTabs({})).toEqual([]);
    expect(
      deskTabs({
        canContent: false,
        canIdentity: false,
        canFeedback: false,
        canReports: false,
      }),
    ).toEqual([]);
  });

  it("身份权限只放出身份桌", () => {
    expect(deskTabs({ canIdentity: true })).toEqual([{ kind: "identity", label: "身份" }]);
  });

  it("内容审核权限展开成新闻 / 活动 / 教程三桌", () => {
    expect(deskTabs({ canContent: true }).map((t) => t.kind)).toEqual([
      "news",
      "activity",
      "tutorial",
    ]);
  });

  it("全部权限时顺序固定：身份 → 内容三桌 → 意见反馈 → 举报案", () => {
    const tabs = deskTabs({
      canContent: true,
      canIdentity: true,
      canFeedback: true,
      canReports: true,
    });
    expect(tabs).toEqual([
      { kind: "identity", label: "身份" },
      { kind: "news", label: "新闻" },
      { kind: "activity", label: "活动" },
      { kind: "tutorial", label: "教程" },
      { kind: "feedback", label: "意见反馈" },
      { kind: "reports", label: "举报案" },
    ]);
  });

  it("只给反馈权限时不出现内容桌", () => {
    expect(deskTabs({ canFeedback: true })).toEqual([
      { kind: "feedback", label: "意见反馈" },
    ]);
  });
});
