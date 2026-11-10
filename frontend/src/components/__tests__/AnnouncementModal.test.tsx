import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import AnnouncementModal from "../AnnouncementModal";
import AnnouncementHost from "../AnnouncementHost";
import type { Announcement } from "../../types/announcements";
import { announcementsApi } from "../../api/announcements";

vi.mock("../../api/announcements", () => ({
  announcementsApi: { active: vi.fn(), get: vi.fn(), markRead: vi.fn() },
}));

vi.mock("../LoginModalProvider", () => ({
  useLoginModal: () => ({ authNonce: 0 }),
}));

// PDF / Word 预览都依赖 canvas 或 fetch 原文件，这里只关心弹窗骨架。
vi.mock("../AnnouncementDocument", () => ({
  __esModule: true,
  default: ({ item }: { item: Announcement }) =>
    item.has_document ? <div data-testid="doc">{item.document_name}</div> : null,
}));

function item(overrides: Partial<Announcement> = {}): Announcement {
  return {
    id: 7,
    title: "关于秋季摄影展报名的通知",
    summary: "第一行\n第二行",
    audience: "all",
    audience_label: "全站（含未登录访客）",
    has_document: true,
    document_kind: "pdf",
    document_name: "秋季摄影展通知.pdf",
    document_size: 486213,
    file_url: "/announcements/7/file/",
    published_at: "2026-10-24T09:00:00+08:00",
    expires_at: null,
    read_at: null,
    created_at: "2026-10-24T08:58:11+08:00",
    ...overrides,
  };
}

describe("AnnouncementModal", () => {
  it("显示标题、发布时间、正文与原件", () => {
    render(<AnnouncementModal item={item()} onClose={() => {}} />);

    const dialog = screen.getByRole("alertdialog", { name: "关于秋季摄影展报名的通知" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("全站公告")).toBeInTheDocument();
    expect(screen.getByText(/发布于/)).toBeInTheDocument();
    expect(screen.getByText(/第一行/)).toBeInTheDocument();
    // 原件区由 AnnouncementDocument 负责（含「下载原件」链接），这里只断言被挂上
    expect(screen.getByTestId("doc")).toHaveTextContent("秋季摄影展通知.pdf");
  });

  it("按 Esc 关闭（关闭即已读）", () => {
    const onClose = vi.fn();
    render(<AnnouncementModal item={item()} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("没有文档时不出渲染区，只有正文", () => {
    render(
      <AnnouncementModal
        item={item({ has_document: false, file_url: null, document_kind: "", document_name: "" })}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByTestId("doc")).not.toBeInTheDocument();
  });
});

describe("AnnouncementHost", () => {
  it("取未读公告 → 关闭即写本地记录并调 markRead → 继续弹下一条", async () => {
    window.localStorage.clear();
    const first = item({ id: 11, title: "第一条" });
    const second = item({ id: 12, title: "第二条", has_document: false, file_url: null });
    (announcementsApi.active as any).mockResolvedValue({ count: 2, results: [first, second] });
    (announcementsApi.markRead as any).mockResolvedValue({ read_at: "x", already_read: false });

    render(<AnnouncementHost />);

    const firstDialog = await screen.findByRole("alertdialog", { name: "第一条" }, { timeout: 3000 });
    expect(firstDialog).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "我知道了" }));

    expect(announcementsApi.markRead).toHaveBeenCalledWith(11);
    expect(window.localStorage.getItem("cobalt:announcement-seen")).toContain("11");

    expect(await screen.findByRole("alertdialog", { name: "第二条" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "我知道了" }));
    expect(announcementsApi.markRead).toHaveBeenCalledWith(12);
  });

  it("已在本机看过的公告不再弹", async () => {
    window.localStorage.clear();
    window.localStorage.setItem("cobalt:announcement-seen", JSON.stringify([21]));
    (announcementsApi.active as any).mockResolvedValue({
      count: 1, results: [item({ id: 21, title: "看过了" })],
    });
    render(<AnnouncementHost />);
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
