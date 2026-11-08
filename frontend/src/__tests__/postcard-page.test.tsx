import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import PostcardPage from "../pages/PostcardPage";
import type { PostcardPortal, PostcardRegistrationSummary } from "../api/postcard";

/**
 * 明信片独立页 smoke：5 阶段渲染分支 + 登记表单交互。
 * 手机壳路径（isMobileDevice=true）绕开桌面 AppShell 的重依赖；
 * API / Turnstile / TabBar 全部 mock，只验证本页逻辑。
 */

vi.mock("../api/postcard", () => ({
  postcardApi: {
    portal: vi.fn(),
    my: vi.fn(),
    register: vi.fn(),
    detail: vi.fn(),
    update: vi.fn(),
    cancel: vi.fn(),
    requestReview: vi.fn(),
    suggest: vi.fn(),
    photoUrl: (id: number, code: string) => `/events/postcard/photo/${id}/?reg_code=${code}`,
    announcementPdfUrl: () => "/events/postcard/announcement-pdf/",
  },
  purgePhotosBeacon: vi.fn(),
}));

vi.mock("../turnstile", () => ({
  useTurnstile: () => ({
    containerRef: { current: null },
    token: "",
    reset: () => {},
    enabled: false,
    policyReady: true,
  }),
}));

vi.mock("../utils/device", () => ({
  isMobileDevice: () => true,
  isAppShell: () => false,
}));

vi.mock("../components/MobileTabBar", () => ({ default: () => null }));

import { postcardApi } from "../api/postcard";

const mockedPortal = vi.mocked(postcardApi.portal);
const mockedMy = vi.mocked(postcardApi.my);

function portalData(overrides: Partial<PostcardPortal> = {}): PostcardPortal {
  return {
    phase: "registering",
    phase_label: "登记中",
    can_register: true,
    is_admin: false,
    sample_ready: true,
    event: {
      id: 1,
      title: "2026 明信片互寄",
      summary: "跨校互寄，见字如面",
      start_at: "2026-11-01T09:00:00+08:00",
      end_at: "2026-12-01T18:00:00+08:00",
    },
    progress: [
      { key: "start", label: "登记开始", time: "2026-11-01T09:00:00+08:00", reached: true },
      { key: "ship", label: "已寄出", time: null, reached: false },
      { key: "distribute", label: "下发中", time: null, reached: false },
      { key: "end", label: "活动结束", time: "2026-12-01T18:00:00+08:00", reached: false },
    ],
    grades: [
      { value: "g1", label: "高一" },
      { value: "g2", label: "高二" },
      { value: "g3", label: "高三" },
    ],
    classes: [1, 2, 3, 4, 5, 6, 7, 8],
    regions: ["浦东新区", "宝山区", "崇明区"],
    schools: [
      { region: "浦东新区", name: "友爱中学" },
      { region: "宝山区", name: "行知中学" },
    ],
    announcement_body: "<p>公告：请规范填写明信片。</p>",
    announcement_pdf: true,
    ...overrides,
  };
}

function regData(overrides: Partial<PostcardRegistrationSummary> = {}): PostcardRegistrationSummary {
  return {
    reg_code: "654321",
    sender_name: "张三",
    grade: "g1",
    grade_label: "高一",
    class_no: 3,
    dest_region: "浦东新区",
    dest_school: "友爱中学",
    status: "registered",
    status_label: "已登记",
    created_at: "2026-11-08T10:00:00+08:00",
    updated_at: "2026-11-08T10:00:00+08:00",
    items: [
      {
        id: 11,
        barcode: "1234567",
        status: "registered",
        status_label: "已登记",
        review_state: "ai_failed",
        review_label: "AI 不匹配",
        mismatched: ["寄达校"],
        comment: "照片显示的学校与填写不符",
        photos: [{ id: 101, side: "front" }, { id: 102, side: "back" }],
      },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PostcardPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockedMy.mockResolvedValue({ results: [] });
});

describe("PostcardPage · 阶段渲染", () => {
  it("未开始：全屏提示，不渲染表单/历史/建议（普通用户）", async () => {
    mockedPortal.mockResolvedValue(portalData({ phase: "not_started", phase_label: "未开始", can_register: false, event: null, progress: [], announcement_body: "", announcement_pdf: false }));
    renderPage();
    expect(await screen.findByText("本年度活动未开始")).toBeTruthy();
    expect(screen.queryByText("明信片登记")).toBeNull();
    expect(screen.queryByText("历史登记记录")).toBeNull();
    expect(screen.queryByText("提建议")).toBeNull();
  });

  it("登记中：公告 + 进度 + 表单 + 历史 + 建议", async () => {
    mockedPortal.mockResolvedValue(portalData());
    renderPage();
    expect(await screen.findByText("2026 明信片互寄")).toBeTruthy();
    expect(screen.getByText("公告：请规范填写明信片。")).toBeTruthy();
    expect(screen.getByText("明信片登记")).toBeTruthy();
    expect(screen.getByText("历史登记记录")).toBeTruthy();
    expect(screen.getByText("提建议")).toBeTruthy();
    expect(screen.getByText("查看公告 PDF")).toBeTruthy();
    // 16 区顺序数据源来自后端，这里只验证下拉渲染了选项
    expect(screen.getAllByRole("option").length).toBeGreaterThan(3);
  });

  it("样例未配置：登记中也不出表单，给联系管理员横幅", async () => {
    mockedPortal.mockResolvedValue(portalData({ sample_ready: false }));
    renderPage();
    expect(await screen.findByText(/填写样例尚未配置/)).toBeTruthy();
    expect(screen.queryByText("明信片登记")).toBeNull();
  });

  it("已寄出：阶段横幅 + 无表单，历史仍可查", async () => {
    mockedPortal.mockResolvedValue(portalData({ phase: "shipped", phase_label: "已寄出", can_register: false }));
    renderPage();
    expect(await screen.findByText("明信片已统一寄出，登记已截止。")).toBeTruthy();
    expect(screen.queryByText("明信片登记")).toBeNull();
    expect(screen.getByText("历史登记记录")).toBeTruthy();
  });

  it("已结束：结束横幅 + 历史可查", async () => {
    mockedPortal.mockResolvedValue(portalData({ phase: "ended", phase_label: "已结束", can_register: false }));
    renderPage();
    expect(await screen.findByText("本次活动已结束，感谢参与！")).toBeTruthy();
    expect(screen.getByText("历史登记记录")).toBeTruthy();
  });
});

describe("PostcardPage · 登记表单交互", () => {
  it("手填 7 位条码入列；重复添加被拦", async () => {
    mockedPortal.mockResolvedValue(portalData());
    renderPage();
    await screen.findByText("明信片登记");

    const input = screen.getByPlaceholderText("或手动输入 7 位条码号");
    fireEvent.change(input, { target: { value: "1234567" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    expect(await screen.findByText("1234567")).toBeTruthy();

    fireEvent.change(input, { target: { value: "1234567" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    expect(await screen.findByText(/已在列表中/)).toBeTruthy();
  });

  it("非数字输入被过滤，凑不齐 7 位无法添加", async () => {
    mockedPortal.mockResolvedValue(portalData());
    renderPage();
    await screen.findByText("明信片登记");

    const input = screen.getByPlaceholderText("或手动输入 7 位条码号");
    fireEvent.change(input, { target: { value: "12a3" } });
    expect((input as HTMLInputElement).value).toBe("123");
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    expect(await screen.findByText(/7 位数字/)).toBeTruthy();
  });
});

describe("PostcardPage · 历史记录", () => {
  it("AI 不匹配条目展示错项与人工复核入口", async () => {
    mockedPortal.mockResolvedValue(portalData());
    mockedMy.mockResolvedValue({ results: [regData()] });
    renderPage();

    expect(await screen.findByText("654321")).toBeTruthy();
    expect(screen.getByText(/AI 判定以下填写与照片不符/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "申请人工复核" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "修改" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "取消登记" })).toBeTruthy();
  });

  it("空历史给出引导文案", async () => {
    mockedPortal.mockResolvedValue(portalData());
    renderPage();
    await screen.findByText("历史登记记录");
    expect(await screen.findByText(/还没有登记记录/)).toBeTruthy();
  });

  it("待审条目触发轮询刷新历史", async () => {
    mockedPortal.mockResolvedValue(portalData());
    const pending = regData({
      items: [{
        id: 11, barcode: "1234567", status: "registered", status_label: "已登记",
        review_state: "pending", review_label: "待审核", mismatched: [], comment: "", photos: [],
      }],
    });
    mockedMy.mockResolvedValue({ results: [pending] });
    renderPage();
    await screen.findByText("654321");
    // 5s 轮询：用例超时给足窗口，只验证 my 被再次调用
    await waitFor(
      () => expect(mockedMy.mock.calls.length).toBeGreaterThan(1),
      { timeout: 8000 },
    );
  }, 12000);
});

describe("PostcardPage · 登记码发放规则（2026-11-08 用户指定）", () => {
  beforeEach(() => {
    // jsdom 没有 URL.createObjectURL（照片预览用）
    (URL as any).createObjectURL = vi.fn(() => "blob:pc-preview");
  });

  async function fillAndSubmit(container: HTMLElement) {
    fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "李明" } });
    fireEvent.change(screen.getByLabelText("年级"), { target: { value: "g1" } });
    fireEvent.change(screen.getByLabelText("班级"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("寄达区"), { target: { value: "浦东新区" } });
    fireEvent.change(screen.getByLabelText("寄达校"), { target: { value: "友爱中学" } });
    const manual = screen.getByPlaceholderText("或手动输入 7 位条码号");
    fireEvent.change(manual, { target: { value: "1234567" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    const files = container.querySelectorAll<HTMLInputElement>(".pc-item input[type=file]");
    fireEvent.change(files[0], { target: { files: [new File(["f"], "f.jpg", { type: "image/jpeg" })] } });
    fireEvent.change(files[1], { target: { files: [new File(["b"], "b.jpg", { type: "image/jpeg" })] } });
    fireEvent.click(screen.getByRole("button", { name: /提交登记/ }));
    await waitFor(() => expect(vi.mocked(postcardApi.register)).toHaveBeenCalled());
  }

  const reviewingResult = {
    reg_code: "824617",
    message: "登记成功",
    registration: regData(),
    review: { state: "pending", hint: "" },
  };

  it("AI 审核中：先不亮码；轮询到 AI 通过后才亮码", async () => {
    mockedPortal.mockResolvedValue(portalData());
    vi.mocked(postcardApi.register).mockResolvedValue(reviewingResult);
    vi.mocked(postcardApi.detail).mockResolvedValue(regData({
      items: [{
        id: 11, barcode: "1234567", status: "registered", status_label: "已登记",
        review_state: "ai_passed", review_label: "AI 通过", mismatched: [], comment: "", photos: [],
      }],
    }));
    const { container } = renderPage();
    await screen.findByText("明信片登记");

    await fillAndSubmit(container);

    expect(await screen.findByText("照片审核中…")).toBeTruthy();
    expect(screen.queryByText("824617")).toBeNull();
    // 2s 轮询出 AI 通过 → 亮码
    await waitFor(() => expect(screen.getByText("登记成功")).toBeTruthy(), { timeout: 7000 });
    expect(screen.getByText("824617")).toBeTruthy();
  }, 15000);

  it("AI 不可用转人工：不轮询，立即亮码", async () => {
    mockedPortal.mockResolvedValue(portalData());
    vi.mocked(postcardApi.register).mockResolvedValue({
      ...reviewingResult,
      review: { state: "manual_pending", hint: "" },
    });
    const { container } = renderPage();
    await screen.findByText("明信片登记");

    await fillAndSubmit(container);

    expect(await screen.findByText("登记成功")).toBeTruthy();
    expect(screen.getByText("824617")).toBeTruthy();
    expect(screen.getByText(/已转人工复核/)).toBeTruthy();
    expect(vi.mocked(postcardApi.detail)).not.toHaveBeenCalled();
  }, 15000);

  it("AI 判不匹配：不亮码、告知错项；申请人工复核后立即亮码", async () => {
    mockedPortal.mockResolvedValue(portalData());
    vi.mocked(postcardApi.register).mockResolvedValue(reviewingResult);
    vi.mocked(postcardApi.detail).mockResolvedValue(regData()); // ai_failed fixture（mismatched: 寄达校）
    vi.mocked(postcardApi.requestReview).mockResolvedValue({ message: "已提交人工复核，请耐心等待复核结果", count: 1 });
    const { container } = renderPage();
    await screen.findByText("明信片登记");

    await fillAndSubmit(container);

    await waitFor(() => expect(screen.getByText("本次登记未通过审核")).toBeTruthy(), { timeout: 7000 });
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/寄达校/)).toBeTruthy();
    expect(screen.queryByText("824617")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "申请人工复核" }));
    await waitFor(() => expect(vi.mocked(postcardApi.requestReview)).toHaveBeenCalledWith("824617", expect.any(String)));
    expect(await screen.findByText("登记成功")).toBeTruthy();
    expect(screen.getByText("824617")).toBeTruthy();
  }, 20000);
});
