import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { listMock, addMock, renameMock, deleteMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  addMock: vi.fn(),
  renameMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock("../../../api/client", () => ({
  api: {
    memberEquipment: listMock,
    addMemberEquipment: addMock,
    renameMemberEquipment: renameMock,
    deleteMemberEquipment: deleteMock,
  },
}));

import EquipmentPanel from "../EquipmentPanel";

const item = {
  id: 1,
  name: "佳能 EOS R6 相机",
  created_at: "2026-11-10T10:00:00+08:00",
  updated_at: "2026-11-10T10:00:00+08:00",
};

describe("EquipmentPanel（我的设备）", () => {
  it("展示已登记设备与数量", async () => {
    listMock.mockResolvedValueOnce({ limit: 30, items: [item] });
    render(<EquipmentPanel />);
    expect(await screen.findByText("佳能 EOS R6 相机")).toBeInTheDocument();
    expect(screen.getByText("已登记 1 / 30 项")).toBeInTheDocument();
  });

  it("去掉首尾空白后提交新增，并重新加载列表", async () => {
    listMock.mockResolvedValue({ limit: 30, items: [] });
    addMock.mockResolvedValueOnce({ item: { ...item, name: "三脚架" } });
    render(<EquipmentPanel />);

    const input = screen.getByLabelText("物品名");
    fireEvent.change(input, { target: { value: "  三脚架  " } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));

    await waitFor(() => expect(addMock).toHaveBeenCalledWith("三脚架"));
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("空列表给出引导文案", async () => {
    listMock.mockResolvedValueOnce({ limit: 30, items: [] });
    render(<EquipmentPanel />);
    expect(await screen.findByText(/还没有登记设备/)).toBeInTheDocument();
  });
});
