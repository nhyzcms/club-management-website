import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { listMock } = vi.hoisted(() => ({ listMock: vi.fn() }));

vi.mock("../../api/events", () => ({
  eventApi: { list: listMock },
}));
vi.mock("../../components/MobileTabBar", () => ({ default: () => null }));

import MobileEventsPage from "../MobileEventsPage";

const EVENT = {
  id: 7,
  title: "运动会检录",
  summary: "请各项目选手提前 20 分钟到检录处",
  body: "",
  organizer: null,
  start_at: "2026-11-02T08:00:00+08:00",
  end_at: "2026-11-02T17:00:00+08:00",
  status: "scheduled",
  status_label: "待开始",
  visibility: "public",
  visibility_label: "公开",
  module_key: "",
  created_at: "2026-11-01T00:00:00+08:00",
  updated_at: "2026-11-01T00:00:00+08:00",
} as const;

function empty() {
  return { results: [], count: 0, next: null, previous: null };
}

/** 按调用顺序排好响应，再渲染一次（同一测试里不要重复 render，否则会挂两棵树）。 */
function page(...responses: unknown[]) {
  for (const r of responses) listMock.mockResolvedValueOnce(r);
  return render(
    <MemoryRouter initialEntries={["/m/events"]}>
      <MobileEventsPage />
    </MemoryRouter>,
  );
}

function oneEvent() {
  return { results: [EVENT], count: 1, next: null, previous: null };
}

describe("MobileEventsPage（手机版活动列表）", () => {
  beforeEach(() => listMock.mockReset());

  it("列出活动并链到手机版详情", async () => {
    page(oneEvent());
    expect(await screen.findByText("运动会检录")).toBeInTheDocument();
    expect(screen.getByText(/请各项目选手提前/)).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/m/events/7");
  });

  it("没有活动时给空态", async () => {
    page(empty());
    expect(await screen.findByText("暂无活动")).toBeInTheDocument();
  });

  it("切换状态 chip 时带 status 参数重新拉第一页", async () => {
    page(oneEvent(), empty());
    await screen.findByText("运动会检录");
    fireEvent.click(screen.getByRole("tab", { name: "进行中" }));
    await waitFor(() => expect(listMock).toHaveBeenLastCalledWith({ page: "1", status: "active" }));
  });
});
