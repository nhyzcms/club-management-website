import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  clampBarcodeCount,
  errMessage,
  fmtTime,
  groupSchools,
  isoToLocalInput,
  mergeSchools,
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

  it("groupSchools 保持 16 区固定顺序，区内按编号升序", () => {
    const out = groupSchools(
      [
        { region: "黄浦区", name: "光明中学", no: 2 },
        { region: "浦东新区", name: "友爱中学", no: 12 },
        { region: "浦东新区", name: "建平中学", no: 3 },
      ],
      POSTCARD_REGIONS,
    );
    expect(out.map((g) => g.region)).toEqual(["浦东新区", "黄浦区"]);
    expect(out[0].schools.map((s) => s.name)).toEqual(["建平中学", "友爱中学"]);
  });

  it("mergeSchools 同区同名以识别编号为准，其余追加", () => {
    const current = [
      { region: "浦东新区", name: "友爱中学", no: 9 },
      { region: "黄浦区", name: "光明中学", no: 2 },
    ];
    const out = mergeSchools(current, [
      { region: "浦东新区", name: "友爱中学", no: 12 },
      { region: "浦东新区", name: "建平中学", no: 3 },
    ]);
    expect(out.added).toBe(1);
    expect(out.schools).toEqual([
      { region: "浦东新区", name: "友爱中学", no: 12 },
      { region: "黄浦区", name: "光明中学", no: 2 },
      { region: "浦东新区", name: "建平中学", no: 3 },
    ]);
    expect(current[0].no).toBe(9); // 不改入参
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

describe("AI 配置预设", () => {
  afterEach(() => vi.restoreAllMocks());

  it("预设填入服务商参数并从 /models 拉模型列表，「其他」清空回自定义", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    vi.spyOn(postcardAdminApi, "aiConfig").mockResolvedValue({
      configured: false,
      enabled: false,
      ready: false,
      base_url: "",
      model: "",
      extra_headers: {},
      timeout_seconds: 20,
      ip_blacklist: [],
      api_key_set: false,
    });
    vi.spyOn(postcardAdminApi, "aiSamples").mockResolvedValue({
      results: [],
      sample_ready: false,
    });
    const aiModels = vi.spyOn(postcardAdminApi, "aiModels").mockResolvedValue({
      ok: true,
      models: ["deepseek-flash", "deepseek-v4-pro"],
    });

    const { default: AITab } = await import("../components/postcard/admin/AITab");
    render(<AITab />);

    fireEvent.click(await screen.findByRole("button", { name: "DeepSeek" }));
    expect((screen.getByRole("textbox", { name: /模型 ID/ }) as HTMLInputElement).value).toBe(
      "deepseek-flash",
    );
    await waitFor(() => expect(aiModels).toHaveBeenCalledTimes(1));
    expect(aiModels.mock.calls[0][0]).toMatchObject({
      base_url: "https://api.deepseek.com/v1",
    });

    fireEvent.click(screen.getByRole("button", { name: "OpenCode-GO" }));
    expect((screen.getByRole("textbox", { name: /模型 ID/ }) as HTMLInputElement).value).toBe(
      "deepseek-v4.1-flash",
    );
    const headers = screen.getByRole("textbox", {
      name: /自定义请求头/,
    }) as HTMLTextAreaElement;
    expect(headers.value).toContain("x-opencode-session");
    expect(headers.value).toContain("x-opencode-client");

    fireEvent.click(screen.getByRole("button", { name: "其他" }));
    expect((screen.getByRole("textbox", { name: /模型 ID/ }) as HTMLInputElement).value).toBe("");
  });

  it("高级选项默认收起、温度随保存提交，读样例带上草稿参数", async () => {
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    const saved = {
      configured: true,
      enabled: true,
      ready: true,
      base_url: "https://saved.example/v1",
      model: "saved-model",
      extra_headers: {},
      timeout_seconds: 20,
      temperature: 0,
      ip_blacklist: ["喜羊羊"],
      prompt_prefix: "",
      api_key_set: true,
    };
    // 第一次打开是 0；保存后重新拉取（真实后端会带回本次保存的 0.4）。
    vi.spyOn(postcardAdminApi, "aiConfig")
      .mockResolvedValueOnce(saved)
      .mockResolvedValueOnce({ ...saved, temperature: 0.4 })
      .mockResolvedValue({ ...saved, temperature: 0.4 });
    vi.spyOn(postcardAdminApi, "aiSamples").mockResolvedValue({
      results: [{ id: 7, caption: "样例", has_image: true }],
      sample_ready: true,
    });
    vi.spyOn(postcardAdminApi, "aiModels").mockResolvedValue({
      ok: true,
      models: ["saved-model"],
    });
    const explain = vi
      .spyOn(postcardAdminApi, "explainAISample")
      .mockResolvedValue({ text: "理解" });
    const save = vi
      .spyOn(postcardAdminApi, "saveAIConfig")
      .mockResolvedValue({ configured: true });

    const { default: AITab } = await import("../components/postcard/admin/AITab");
    render(<AITab />);

    // Base URL / 模型 ID / 超时 / 温度 / 请求头都收进「高级选项」，且默认收起。
    const details = (await screen.findByText(/高级选项/)).closest("details") as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("Base URL");

    fireEvent.change(screen.getByRole("spinbutton", { name: "温度" }), {
      target: { value: "0.4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存 AI 配置" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toMatchObject({ temperature: 0.4 });

    // 「让 AI 读样例」与「测试连接」同口径：带上当前草稿参数（后端不落库）。
    fireEvent.click(screen.getByRole("button", { name: "让 AI 读样例" }));
    await waitFor(() => expect(explain).toHaveBeenCalled());
    expect(explain.mock.calls[0][1]).toMatchObject({
      base_url: "https://saved.example/v1",
      model: "saved-model",
      temperature: 0.4,
    });
    expect(await screen.findByText("理解")).toBeTruthy();
  });

  it("前置提示词是多行文本，随保存一起提交", async () => {
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    vi.spyOn(postcardAdminApi, "aiConfig").mockResolvedValue({
      configured: true,
      enabled: true,
      ready: true,
      base_url: "",
      model: "demo-model",
      extra_headers: {},
      timeout_seconds: 20,
      ip_blacklist: [],
      prompt_prefix: "第一行\n第二行",
      api_key_set: true,
    });
    vi.spyOn(postcardAdminApi, "aiSamples").mockResolvedValue({
      results: [],
      sample_ready: true,
    });
    const save = vi
      .spyOn(postcardAdminApi, "saveAIConfig")
      .mockResolvedValue({ configured: true });

    const { default: AITab } = await import("../components/postcard/admin/AITab");
    render(<AITab />);

    const box = (await screen.findByRole("textbox", {
      name: /前置提示词/,
    })) as HTMLTextAreaElement;
    expect(box.tagName).toBe("TEXTAREA");
    expect(box.value).toBe("第一行\n第二行");

    fireEvent.change(box, { target: { value: "新的\n提示词" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 AI 配置" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toMatchObject({ prompt_prefix: "新的\n提示词" });
  });

  it("「测试连接」带当前填写（未保存）的参数，而不是只发空对象", async () => {
    const { postcardAdminApi } = await import("../api/postcardAdmin");
    vi.spyOn(postcardAdminApi, "aiConfig").mockResolvedValue({
      configured: false,
      enabled: false,
      ready: false,
      base_url: "",
      model: "",
      extra_headers: {},
      timeout_seconds: 20,
      ip_blacklist: [],
      api_key_set: false,
    });
    vi.spyOn(postcardAdminApi, "aiSamples").mockResolvedValue({
      results: [],
      sample_ready: false,
    });
    vi.spyOn(postcardAdminApi, "aiModels").mockResolvedValue({ ok: true, models: [] });
    const testAI = vi.spyOn(postcardAdminApi, "testAIConfig").mockResolvedValue({
      ok: true,
      latency_ms: 12,
      model: "deepseek-flash",
      reply: "pong",
    });

    const { default: AITab } = await import("../components/postcard/admin/AITab");
    render(<AITab />);
    fireEvent.click(await screen.findByRole("button", { name: "DeepSeek" }));
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));

    await waitFor(() => expect(testAI).toHaveBeenCalledTimes(1));
    expect(testAI.mock.calls[0][0]).toMatchObject({
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-flash",
      timeout_seconds: 60,
    });
  });
});
