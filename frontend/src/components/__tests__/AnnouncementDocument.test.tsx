import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AnnouncementDocument from "../AnnouncementDocument";
import type { Announcement } from "../../types/announcements";

vi.mock("../PdfPreview", () => ({
  __esModule: true,
  default: ({ url }: { url: string }) => <div data-testid="pdf">{url}</div>,
}));

function item(overrides: Partial<Announcement> = {}): Announcement {
  return {
    id: 9,
    title: "通知",
    summary: "",
    audience: "all",
    audience_label: "全站",
    has_document: true,
    document_kind: "pdf",
    document_name: "通知.pdf",
    document_size: 2048,
    file_url: "/announcements/9/file/",
    published_at: null,
    expires_at: null,
    read_at: null,
    created_at: "2026-10-24T09:00:00+08:00",
    ...overrides,
  };
}

describe("AnnouncementDocument", () => {
  it("PDF 交给 PdfPreview，并给出原件下载链接（含大小）", () => {
    render(<AnnouncementDocument item={item()} />);
    expect(screen.getByTestId("pdf")).toHaveTextContent("/announcements/9/file/");
    const link = screen.getByRole("link", { name: /下载原件/ });
    expect(link).toHaveAttribute("href", "/announcements/9/file/");
    expect(link).toHaveAttribute("download", "通知.pdf");
    expect(link).toHaveTextContent("2 KB");
  });

  it("没有文档时什么都不渲染", () => {
    const { container } = render(
      <AnnouncementDocument item={item({ has_document: false, file_url: null })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
