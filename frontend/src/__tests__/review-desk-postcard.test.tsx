import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { deskTabs } from "../utils/reviewDesk";
import PostcardReviewPane from "../pages/review/PostcardReviewPane";
import type { ReviewRow } from "../api/postcardAdmin";

/**
 * 明信片并入审核台（2026-11-08 用户要求）：
 * 1) 有复核权限就出现「明信片」桌；
 * 2) 桌内卡片展示条码/寄出人/AI 判定，并能提交通过/不通过。
 */

vi.mock("../api/postcardAdmin", async () => {
  const actual = await vi.importActual<typeof import("../api/postcardAdmin")>("../api/postcardAdmin");
  return {
    ...actual,
    postcardAdminApi: {
      ...actual.postcardAdminApi,
      reviewPhotoUrl: (id: number) => `/events/postcard/photo/${id}/`,
      reviewDecision: vi.fn(),
    },
  };
});

const row: ReviewRow = {
  id: 7,
  item_id: 7,
  barcode: "1234567",
  review_state: "manual_pending",
  photo_ids: [],
  ai_verdict: {
    matched: false,
    mismatched_items: ["寄达校"],
    blacklist_hit: false,
    blacklist_names: [],
    comment: "照片与填写不一致",
  },
  registration: {
    registration_id: 3,
    reg_code: "654321",
    sender_name: "张三",
    grade_label: "高一",
    class_no: 3,
    dest_region: "浦东新区",
    dest_school: "友爱中学",
    created_at: "2026-11-08T10:00:00+08:00",
  },
};

describe("审核台 · 明信片桌", () => {
  it("有复核权限时出现「明信片」桌", () => {
    const tabs = deskTabs({ canPostcard: true });
    expect(tabs.map((t) => t.kind)).toContain("postcard");
    expect(tabs.find((t) => t.kind === "postcard")?.label).toBe("明信片");
  });

  it("没有复核权限时不出现", () => {
    expect(deskTabs({ canContent: true }).map((t) => t.kind)).not.toContain("postcard");
  });

  it("卡片展示 AI 错项，通过时带上备注", () => {
    const onDecision = vi.fn();
    render(
      <PostcardReviewPane
        item={row}
        busy={false}
        onDecision={onDecision}
        onNext={() => {}}
        onLightbox={() => {}}
      />,
    );
    expect(screen.getByText(/张三/)).toBeTruthy();
    expect(screen.getByText(/寄达校/)).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText(/照片与填写/), {
      target: { value: "已电话核对" },
    });
    fireEvent.click(screen.getByRole("button", { name: "通过" }));
    expect(onDecision).toHaveBeenCalledWith("pass", "已电话核对");

    fireEvent.click(screen.getByRole("button", { name: "不通过" }));
    expect(onDecision).toHaveBeenCalledWith("fail", "已电话核对");
  });
});
