import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { PostcardPortal } from "../api/postcard";
import type { ReceiptPayload } from "../api/postcardAdmin";

/**
 * 明信片条码号输入框的自动聚焦（2026-11-11 用户要求）：
 *
 * - 签收页 / 登记页进页面就把光标放进条码号框（硬件扫码枪开箱可用）；
 * - 只在桌面端抢焦点 —— 手机端聚焦会立刻弹软键盘，把姓名等字段顶出屏幕；
 * - 签收确认成功后清空并回焦，便于连续签收。
 */

const mobile = { value: false };
vi.mock("../utils/device", () => ({
  isMobileDevice: () => mobile.value,
  isAppShell: () => false,
}));

const receipt = vi.fn();
const statusByToken = vi.fn();
vi.mock("../api/postcardAdmin", () => ({
  postcardAdminApi: {
    lookup: (...args: unknown[]) => receipt("lookup", args),
    confirm: (...args: unknown[]) => receipt("confirm", args),
    unreport: (...args: unknown[]) => receipt("unreport", args),
  },
}));

const register = vi.fn();
vi.mock("../api/postcard", () => ({
  postcardApi: {
    register: (...args: unknown[]) => register(...args),
    statusByToken: (...args: unknown[]) => statusByToken(...args),
    portal: vi.fn(),
    my: vi.fn(),
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

vi.mock("../postcardSim/session", () => ({
  enterSim: () => {},
  isSimMode: () => false,
  isSimRoute: () => false,
}));

vi.mock("../components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import RegisterForm from "../components/postcard/RegisterForm";
import PostcardReceivePage from "../pages/PostcardReceivePage";

function portal(): PostcardPortal {
  return {
    grades: [{ value: "g1", label: "高一" }],
    classes: [1, 2],
    regions: ["浦东新区"],
    schools: [{ region: "浦东新区", name: "建平中学", no: 1 }],
  } as unknown as PostcardPortal;
}

function payload(status = "registered"): ReceiptPayload {
  return {
    barcode: "1234567",
    item_status: status,
    item_status_label: status === "reported" ? "已报寄" : "已登记",
    registration: {
      reg_code: "832145",
      sender_name: "张三",
      grade_label: "高一",
      class_no: 3,
      dest_region: "浦东新区",
      dest_school: "建平中学",
      status: "registered",
      status_label: "已登记",
      created_at: "2026-11-10T08:00:00Z",
    },
  };
}

/** 手机端走 MobilePage（内部用 useNavigate），所以统一套一层 MemoryRouter。 */
function renderReceive() {
  return render(
    <MemoryRouter>
      <PostcardReceivePage />
    </MemoryRouter>,
  );
}

function barcodeInput(): HTMLInputElement {
  return screen.getByPlaceholderText("或手动输入 7 位条码号") as HTMLInputElement;
}

function receiveInput(): HTMLInputElement {
  return screen.getByLabelText("条码号") as HTMLInputElement;
}

beforeEach(() => {
  mobile.value = false;
  receipt.mockReset();
  register.mockReset();
});

describe("登记页条码号框", () => {
  it("桌面端进页面即聚焦条码号框", () => {
    render(
      <RegisterForm portal={portal()} fingerprint="fp" isMobile={false} onRegistered={() => {}} />,
    );
    expect(barcodeInput()).toHaveFocus();
  });

  it("手机端不抢焦点（避免一进页弹软键盘）", () => {
    render(
      <RegisterForm portal={portal()} fingerprint="fp" isMobile onRegistered={() => {}} />,
    );
    expect(barcodeInput()).not.toHaveFocus();
  });

  it("focusSignal 自增后把光标还给条码号框", () => {
    const { rerender } = render(
      <RegisterForm
        portal={portal()}
        fingerprint="fp"
        isMobile={false}
        focusSignal={0}
        onRegistered={() => {}}
      />,
    );
    barcodeInput().blur();
    expect(barcodeInput()).not.toHaveFocus();
    rerender(
      <RegisterForm
        portal={portal()}
        fingerprint="fp"
        isMobile={false}
        focusSignal={1}
        onRegistered={() => {}}
      />,
    );
    expect(barcodeInput()).toHaveFocus();
  });
});

describe("签收页条码号框", () => {
  it("桌面端进页面即聚焦", () => {
    receipt.mockResolvedValue(payload());
    renderReceive();
    expect(receiveInput()).toHaveFocus();
  });

  it("手机端不抢焦点", () => {
    mobile.value = true;
    receipt.mockResolvedValue(payload());
    renderReceive();
    expect(receiveInput()).not.toHaveFocus();
  });

  it("确认签收后清空条码框并回焦", async () => {
    receipt.mockImplementation((method: string, args: unknown[]) => {
      if (method === "lookup") return Promise.resolve(payload());
      if (method === "confirm") return Promise.resolve(payload("reported"));
      return Promise.resolve(payload());
    });
    renderReceive();

    fireEvent.change(receiveInput(), { target: { value: "1234567" } });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));
    const confirmBtn = await screen.findByRole("button", { name: "确认签收" });
    confirmBtn.focus();
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(receiveInput().value).toBe(""));
    expect(receiveInput()).toHaveFocus();
  });
});
