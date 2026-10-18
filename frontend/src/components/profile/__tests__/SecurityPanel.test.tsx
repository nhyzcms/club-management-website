import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const { statusMock, questionsMock, eventsMock } = vi.hoisted(() => ({
  statusMock: vi.fn(),
  questionsMock: vi.fn(),
  eventsMock: vi.fn(() => Promise.resolve({ results: [] })),
}));

vi.mock("../../../api/stepup", () => ({
  stepupApi: { status: statusMock, questions: questionsMock, events: eventsMock, questionsSet: vi.fn() },
  redirectToStepUp: vi.fn(),
}));

import SecurityPanel from "../SecurityPanel";

describe("SecurityPanel（安全验证面板）", () => {
  it("未设置问题：展示设置入口与首设说明", async () => {
    statusMock.mockResolvedValueOnce({
      scopes: {},
      email: { available: true, address: "u***@x.com", cooldown_remaining: 0 },
      questions: { configured: false, count: 0 },
      grant_ttl: 600,
    });
    questionsMock.mockResolvedValueOnce({ bank: [{ key: "primary_school", text: "你小学的名称是？" }], mine: [] });
    render(<SecurityPanel />);
    expect(await screen.findByRole("button", { name: "设置安全问题" })).toBeInTheDocument();
    expect(screen.getByText(/首次设置需输入/)).toBeInTheDocument();
  });

  it("已设置：列出题干与更换入口", async () => {
    statusMock.mockResolvedValueOnce({
      scopes: {},
      email: { available: false, address: "", cooldown_remaining: 0 },
      questions: { configured: true, count: 1 },
      grant_ttl: 600,
    });
    questionsMock.mockResolvedValueOnce({
      bank: [],
      mine: [{ id: 7, key: "primary_school", text: "你小学的名称是？" }],
    });
    render(<SecurityPanel />);
    expect(await screen.findByText("你小学的名称是？")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更换安全问题" })).toBeInTheDocument();
    expect(screen.getByText(/邮箱验证码：不可用/)).toBeInTheDocument();
  });
});
