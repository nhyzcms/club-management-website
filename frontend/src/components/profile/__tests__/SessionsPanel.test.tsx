import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { listSessionsMock, revokeSessionMock, revokeOthersMock } = vi.hoisted(() => ({
  listSessionsMock: vi.fn(),
  revokeSessionMock: vi.fn(),
  revokeOthersMock: vi.fn(),
}));

vi.mock("../../../api/client", () => ({
  api: {
    listSessions: listSessionsMock,
    revokeSession: revokeSessionMock,
    revokeOtherSessions: revokeOthersMock,
  },
}));

import SessionsPanel from "../SessionsPanel";

const payload = (overrides: Record<string, unknown> = {}) => ({
  max_active: 3,
  active_count: 2,
  results: [
    {
      id: 11,
      device_name: "Chrome · Windows",
      device_type: "Desktop",
      client_kind: "web",
      ip_address: "8.8.8.8",
      created_at: "2026-10-24T10:00:00+08:00",
      last_seen_at: "2026-10-24T10:05:00+08:00",
      is_active: true,
      is_this_device: true,
      revoked_at: null,
      revoked_reason: "",
    },
    {
      id: 12,
      device_name: "Safari · iOS",
      device_type: "Mobile",
      client_kind: "app",
      ip_address: "1.1.1.1",
      created_at: "2026-10-24T09:00:00+08:00",
      last_seen_at: "2026-10-24T09:30:00+08:00",
      is_active: true,
      is_this_device: false,
      revoked_at: null,
      revoked_reason: "",
    },
    {
      id: 13,
      device_name: "Firefox · Linux",
      device_type: "Desktop",
      client_kind: "web",
      ip_address: null,
      created_at: "2026-10-23T09:00:00+08:00",
      last_seen_at: null,
      is_active: false,
      is_this_device: false,
      revoked_at: "2026-10-24T08:00:00+08:00",
      revoked_reason: "limit",
    },
  ],
  ...overrides,
});

describe("SessionsPanel（登录设备 / 多端登录）", () => {
  it("展示名额、在线设备与下线历史", async () => {
    listSessionsMock.mockResolvedValueOnce(payload());
    render(<SessionsPanel />);

    expect(await screen.findByText(/在线 2 \/ 3/)).toBeInTheDocument();
    expect(screen.getByText("Chrome · Windows")).toBeInTheDocument();
    expect(screen.getByText("本机")).toBeInTheDocument();
    expect(screen.getByText("App")).toBeInTheDocument();
    // 已下线历史默认折叠，但条目存在
    expect(screen.getByText(/最近下线记录（1）/)).toBeInTheDocument();
    expect(screen.getByText(/名额已满被替换/)).toBeInTheDocument();
  });

  it("下线其他设备：二次确认后调用 revoke-others 并刷新", async () => {
    listSessionsMock.mockResolvedValue(payload());
    revokeOthersMock.mockResolvedValueOnce({ revoked: 1, active_count: 1, max_active: 3 });
    render(<SessionsPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "下线其他所有设备" }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部下线" }));

    await waitFor(() => expect(revokeOthersMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(listSessionsMock).toHaveBeenCalledTimes(2));
  });

  it("下线单台设备：确认后带上记录 id", async () => {
    listSessionsMock.mockResolvedValue(payload());
    revokeSessionMock.mockResolvedValueOnce({ revoked: true, was_current: false });
    render(<SessionsPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "下线" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认下线" }));

    await waitFor(() => expect(revokeSessionMock).toHaveBeenCalledWith(12));
    await waitFor(() => expect(listSessionsMock).toHaveBeenCalledTimes(2));
  });
});
