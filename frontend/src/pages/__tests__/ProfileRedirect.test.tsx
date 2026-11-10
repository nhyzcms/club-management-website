import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";

const { meMock } = vi.hoisted(() => ({ meMock: vi.fn() }));

vi.mock("../../api/client", () => ({ api: { me: meMock } }));
vi.mock("../../components/LoginModalProvider", () => {
  const openLogin = vi.fn();
  return { useLoginModal: () => ({ openLogin }) };
});

import ProfileRedirect from "../ProfileRedirect";

function Probe() {
  const { id } = useParams();
  const location = useLocation();
  return (
    <div data-testid="probe">
      {id}
      {location.search}
    </div>
  );
}

describe("ProfileRedirect（/profile → /u/:id）", () => {
  it("保留 query（?tab=password）——安全验证回跳恢复表单依赖此行为", async () => {
    meMock.mockResolvedValueOnce({ user: { id: 5 } });
    render(
      <MemoryRouter initialEntries={["/profile?tab=password"]}>
        <Routes>
          <Route path="/profile" element={<ProfileRedirect />} />
          <Route path="/u/:id" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    const probe = await screen.findByTestId("probe");
    expect(probe).toHaveTextContent("5");
    expect(probe).toHaveTextContent("?tab=password");
  });

  it("无 query 时也正常跳转", async () => {
    meMock.mockResolvedValueOnce({ user: { id: 7 } });
    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <Routes>
          <Route path="/profile" element={<ProfileRedirect />} />
          <Route path="/u/:id" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("probe")).toHaveTextContent("7");
  });
});
