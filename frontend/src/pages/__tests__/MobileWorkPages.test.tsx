import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/**
 * 手机版工作台的冒烟测试：确认页面能挂载、权限门禁生效、队列为空时
 * 给出正确空态。数据层全部 mock，不发真实请求（2 核生产机也不该跑测试）。
 */

// vi.mock 的工厂会被提升到文件顶部，共享的 mock 函数必须用 vi.hoisted 建。
const { listEmpty } = vi.hoisted(() => ({
  listEmpty: vi.fn(() => Promise.resolve({ results: [], next: null, count: 0 })),
}));

vi.mock("../../api/client", () => ({
  api: {
    me: vi.fn(() =>
      Promise.resolve({
        user: { id: 1, username: "u", permissions: {} },
        profile: { nickname: "U", is_verified: true },
        role: { label: "用户", variant: "user" },
      }),
    ),
  },
}));

vi.mock("../../api/unreadBadges", () => ({
  useUnreadCounts: () => ({ signedIn: true, dm: 0, notif: 0 }),
  formatUnreadCount: (n: number) => String(n),
}));

vi.mock("../../api/identityReviews", () => ({
  identityReviewsApi: { list: listEmpty, approve: vi.fn(), reject: vi.fn(), disable: vi.fn() },
}));
vi.mock("../../api/reviews", () => ({
  reviewsApi: { list: listEmpty, approve: vi.fn(), reject: vi.fn(), remove: vi.fn() },
}));
vi.mock("../../api/feedback", () => ({
  feedbackApi: { list: listEmpty, get: vi.fn(), close: vi.fn() },
}));
vi.mock("../../api/reports", () => ({
  reportsApi: { list: listEmpty, dismiss: vi.fn(), uphold: vi.fn() },
}));

vi.mock("../../api/tasks", () => ({
  taskApi: {
    list: vi.fn(() =>
      Promise.resolve({
        results: [
          {
            id: 7,
            title: "整理素材库",
            status: "pending",
            priority: "high",
            creator: { id: 1, username: "u", nickname: "U", email: "", avatar: null },
            assignee: null,
            tags: [],
            completed_at: null,
            reject_reason: "",
            attachment_count: 2,
            created_at: "2026-10-01T00:00:00Z",
            updated_at: "2026-10-01T00:00:00Z",
          },
        ],
        count: 1,
        next: null,
      }),
    ),
    get: vi.fn(),
  },
}));

import MobileReviewPage from "../MobileReviewPage";
import MobileTaskListPage from "../MobileTaskListPage";

describe("手机版审核台", () => {
  it("没有审核能力时直接说明无权限", async () => {
    render(
      <MemoryRouter>
        <MobileReviewPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("你没有审核权限。")).toBeInTheDocument();
  });
});

describe("手机版任务列表", () => {
  it("渲染任务卡片与筛选 chip", async () => {
    render(
      <MemoryRouter>
        <MobileTaskListPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("整理素材库")).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "任务状态" })).toBeInTheDocument();
  });
});
