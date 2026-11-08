import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import {
  clampBarcodeCount,
  errMessage,
  fmtTime,
  groupSchools,
  isoToLocalInput,
  localInputToIso,
  verdictSummary,
} from "../components/postcard/admin/pure";
import { POSTCARD_REGIONS } from "../api/postcardAdmin";

/**
 * 明信片管理端：纯函数全覆盖 + 一个轻量组件 smoke。
 *
 * 配置 tab 依赖 tiptap 富文本（jsdom 下成本高、价值低），
 * 由 e2e / 人工截图覆盖；这里只钉住「数字与文案」这类易回归的逻辑。
 */

vi.mock("../api/postcardAdmin", async () => {
  const actual = await vi.importActual<typeof import("../api/postcardAdmin")>("../api/postcardAdmin");
  return {
    ...actual,
    postcardAdminApi: {
      ...actual.postcardAdminApi,
      barcodes: vi.fn(),
      generateBarcodes: vi.fn(),
    },
  };
});

describe("管理端纯函数", () => {
  it("isoToLocalInput / localInputToIso 往返（分钟精度）", () => {
    const local = "2026-11-20T09:30";
    const iso = localInputToIso(local);
    expect(iso).toBeTruthy();
    expect(isoToLocalInput(iso)).toBe(local);
    expect(localInputToIso("")).toBeNull();
    expect(isoToLocalInput(null)).toBe("");
    expect(isoToLocalInput("不是时间")).toBe("");
  });

  it("clampBarcodeCount 夹在区间并对齐步进", () => {
    expect(clampBarcodeCount(100, 1500, 10000, 500)).toBe(1500);
    expect(clampBarcodeCount(999999, 1500, 10000, 500)).toBe(10000);
    expect(clampBarcodeCount(6123, 1500, 10000, 500)).toBe(6000);
    expect(clampBarcodeCount(Number.NaN, 1500, 10000, 500)).toBe(1500);
  });

  it("groupSchools 保持 16 区固定顺序，区内保持录入顺序", () => {
    const out = groupSchools(
      [
        { region: "黄浦区", name: "光明中学" },
        { region: "浦东新区", name: "友爱中学" },
        { region: "浦东新区", name: "建平中学" },
      ],
      POSTCARD_REGIONS,
    );
    expect(out.map((g) => g.region)).toEqual(["浦东新区", "黄浦区"]);
    expect(out[0].names).toEqual(["友爱中学", "建平中学"]);
  });

  it("verdictSummary 兼容 AI 原始判定与人工改判后的复合结构", () => {
    const ai = verdictSummary({
      matched: false,
      mismatched_items: ["寄达校"],
      blacklist_hit: true,
      blacklist_names: ["某形象"],
      comment: "照片与填写不一致",
    });
    expect(ai).not.toBeNull();
    expect(ai!.matched).toBe(false);
    expect(ai!.mismatched).toEqual(["寄达校"]);
    expect(ai!.blacklist).toEqual(["某形象"]);

    const manual = verdictSummary({
      manual: { decision: "pass", note: "人工确认无误", by: "admin" },
      ai_verdict: { matched: false, mismatched_items: ["寄达区"] },
    });
    expect(manual!.manual).toContain("人工通过");
    expect(manual!.mismatched).toEqual(["寄达区"]);

    expect(verdictSummary(null)).toBeNull();
  });

  it("errMessage 把 403 与网络异常落成人话", () => {
    expect(errMessage({ apiError: { kind: "forbidden" }, message: "" })).toContain("没有权限");
    expect(errMessage({ apiError: { kind: "network" } })).toContain("网络异常");
    expect(errMessage({ message: "结束时间必须晚于开始时间" })).toBe("结束时间必须晚于开始时间");
    expect(errMessage({ status: 500 })).toContain("500");
  });

  it("fmtTime 空值与非法值给占位符", () => {
    expect(fmtTime(null)).toBe("—");
    expect(fmtTime("")).toBe("—");
    expect(fmtTime("oops")).toBe("—");
    expect(fmtTime(new Date(2026, 10, 8, 9, 5).toISOString())).toBe("2026-11-08 09:05");
  });
});

describe("BarcodeTab", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("展示现有条码数并能打开导出入口", async () => {
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    (postcardAdminApi.barcodes as any).mockResolvedValue({
      configured: true,
      total: 6200,
      min: 1500,
      max: 10000,
      step: 500,
      default: 6000,
    });
    const { default: BarcodeTab } = await import("../components/postcard/admin/BarcodeTab");
    render(<BarcodeTab />);
    await waitFor(() => expect(screen.getByText("6200")).toBeTruthy());
    const btn = screen.getByRole("button", { name: "下载整版 PDF" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    // 已有条码时主按钮是「继续生成」，不是「生成」
    expect(screen.getByRole("button", { name: "继续生成条码" })).toBeTruthy();
  });

  it("数量按加减号步进，不能自由输入", async () => {
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    (postcardAdminApi.barcodes as any).mockResolvedValue({
      configured: true,
      total: 0,
      bound: 0,
      min: 1500,
      max: 10000,
      step: 500,
      default: 6000,
    });
    const { default: BarcodeTab } = await import("../components/postcard/admin/BarcodeTab");
    render(<BarcodeTab />);
    await waitFor(() => expect(screen.getByRole("button", { name: "生成条码" })).toBeTruthy());
    expect(screen.queryByRole("spinbutton")).toBeNull();
    (screen.getByRole("button", { name: "增加 500 个" }) as HTMLButtonElement).click();
    await waitFor(() => expect(screen.getByText("6500")).toBeTruthy());
    (screen.getByRole("button", { name: "减少 500 个" }) as HTMLButtonElement).click();
    await waitFor(() => expect(screen.getByText("6000")).toBeTruthy());
  });

  it("覆盖生成要二次确认后才调接口", async () => {
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    (postcardAdminApi.barcodes as any).mockResolvedValue({
      configured: true,
      total: 6200,
      bound: 0,
      min: 1500,
      max: 10000,
      step: 500,
      default: 6000,
    });
    (postcardAdminApi.generateBarcodes as any).mockResolvedValue({
      generated: 6000,
      total: 6000,
      replaced: true,
    });
    const { default: BarcodeTab } = await import("../components/postcard/admin/BarcodeTab");
    render(<BarcodeTab />);
    await waitFor(() => expect(screen.getByText("6200")).toBeTruthy());
    (screen.getByRole("button", { name: "覆盖生成新条码" }) as HTMLButtonElement).click();
    await waitFor(() => expect(screen.getByRole("alertdialog")).toBeTruthy());
    expect(postcardAdminApi.generateBarcodes).not.toHaveBeenCalled();
    (screen.getByRole("button", { name: "覆盖生成" }) as HTMLButtonElement).click();
    await waitFor(() =>
      expect(postcardAdminApi.generateBarcodes).toHaveBeenCalledWith(6000, true),
    );
  });

  it("已有条码被登记占用时禁用覆盖生成", async () => {
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    (postcardAdminApi.barcodes as any).mockResolvedValue({
      configured: true,
      total: 6200,
      bound: 3,
      min: 1500,
      max: 10000,
      step: 500,
      default: 6000,
    });
    const { default: BarcodeTab } = await import("../components/postcard/admin/BarcodeTab");
    render(<BarcodeTab />);
    await waitFor(() => expect(screen.getByText("6200")).toBeTruthy());
    const btn = screen.getByRole("button", { name: "覆盖生成新条码" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByText(/已有 3 个条码被登记占用/)).toBeTruthy();
  });
});
