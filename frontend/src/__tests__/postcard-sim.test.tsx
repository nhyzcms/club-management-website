import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  barcodeSummary,
  configPayload,
  emptySimState,
  generateBarcodes,
  newSeason,
  phaseOf,
  publish,
  pushAudit,
  saveConfig,
  statsOf,
  updateRegistration,
  type SimConfig,
  type SimEvent,
  type SimState,
} from "../postcardSim/state";
import { buildPdf, buildXlsx, bytesToDataUrl } from "../postcardSim/files";
import { isSimRoute } from "../postcardSim/session";
import { isPostcardAdminSim, withSimFileSuffix } from "../api/postcardAdmin";
import PostcardAdminPage from "../pages/PostcardAdminPage";

/**
 * 模拟环境（`?sim=1`）：纯函数 + 文件生成 + 入口/徽标。
 *
 * 重点钉住三条线：
 * 1. 阶段 / 条码 / 校验口径与后端一致（不一致就等于教错人）；
 * 2. 导出的 PDF / xlsx 是真文件（文件名带「仅限模拟环境使用」）；
 * 3. 入口 / 徽标文案，以及「模拟态只靠内存」的安装与卸载。
 */

// jsdom 没有 scrollIntoView（页面里 tab 高亮会调用），补个空实现。
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {});

// 组件测试：AppShell / 富文本 tab 都换成空壳（tiptap 在 jsdom 里又慢又无价值）。
vi.mock("../components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../components/postcard/admin/ConfigTab", () => ({ default: () => <div>config-tab</div> }));
vi.mock("../components/postcard/admin/BarcodeTab", () => ({ default: () => <div>barcode-tab</div> }));
vi.mock("../components/postcard/admin/AITab", () => ({ default: () => <div>ai-tab</div> }));
vi.mock("../components/postcard/admin/RecordsTab", () => ({ default: () => <div>records-tab</div> }));
vi.mock("../components/postcard/admin/StatsTab", () => ({ default: () => <div>stats-tab</div> }));
vi.mock("../components/postcard/admin/MiscTab", () => ({ default: () => <div>misc-tab</div> }));
vi.mock("../utils/device", () => ({ isMobileDevice: () => false }));

const EVENT: SimEvent = {
  id: 1,
  title: "2026 明信片互寄",
  summary: "",
  status: "published",
  start_at: "2026-11-01T00:00:00.000Z",
  end_at: "2026-12-01T00:00:00.000Z",
};
const CONFIG: SimConfig = {
  ship_at: "2026-11-20T00:00:00.000Z",
  distribute_at: "2026-11-25T00:00:00.000Z",
  allowed_grades: ["g1"],
  destination_schools: [],
  announcement_body: "",
  has_announcement_pdf: false,
};

function at(iso: string): Date {
  return new Date(iso);
}

function seeded(): SimState {
  const state = emptySimState();
  saveConfig(
    state,
    {
      title: EVENT.title,
      summary: "",
      body: "",
      start_at: EVENT.start_at,
      end_at: EVENT.end_at as string,
      ship_at: CONFIG.ship_at,
      distribute_at: CONFIG.distribute_at,
      allowed_grades: ["g1"],
      destination_schools: [],
    },
    {},
    at("2026-10-01T00:00:00.000Z"),
  );
  publish(state);
  return state;
}

afterEach(() => {
  window.location.hash = "";
});

describe("模拟环境 · 阶段推导（对齐后端 state.py）", () => {
  it("未配置 / 草稿 → 未开始", () => {
    expect(phaseOf(null, null)).toBe("not_started");
    const draft = { ...EVENT, status: "draft" as const };
    expect(phaseOf(draft, CONFIG, at("2026-11-10T00:00:00Z"))).toBe("not_started");
  });

  it("按节点时间推进：未开始 → 登记中 → 已寄出 → 下发中 → 已结束", () => {
    expect(phaseOf(EVENT, CONFIG, at("2026-10-20T00:00:00Z"))).toBe("not_started");
    expect(phaseOf(EVENT, CONFIG, at("2026-11-10T00:00:00Z"))).toBe("registering");
    expect(phaseOf(EVENT, CONFIG, at("2026-11-21T00:00:00Z"))).toBe("shipped");
    expect(phaseOf(EVENT, CONFIG, at("2026-11-26T00:00:00Z"))).toBe("distributing");
    expect(phaseOf(EVENT, CONFIG, at("2026-12-02T00:00:00Z"))).toBe("ended");
  });

  it("节点留空 = 跳过该阶段；归档 → 已结束", () => {
    const skipped = { ...CONFIG, ship_at: null, distribute_at: null };
    expect(phaseOf(EVENT, skipped, at("2026-11-10T00:00:00Z"))).toBe("registering");
    expect(phaseOf({ ...EVENT, status: "archived" }, CONFIG, at("2026-11-10T00:00:00Z"))).toBe("ended");
  });
});

describe("模拟环境 · 配置与条码", () => {
  it("保存配置后 configured=true 且阶段按时间推导", () => {
    const state = seeded();
    const payload = configPayload(state, at("2026-11-10T00:00:00Z"));
    expect(payload.configured).toBe(true);
    expect(payload.event?.status).toBe("published");
    expect(payload.phase_label).toBe("登记中");
  });

  it("缺标题 / 时间 / 年级会被拒（口径同后端）", () => {
    const state = emptySimState();
    const base = {
      title: "",
      summary: "",
      body: "",
      start_at: "",
      end_at: "",
      ship_at: null,
      distribute_at: null,
      allowed_grades: ["g1"],
      destination_schools: [],
    };
    expect(() => saveConfig(state, { ...base, title: "标题" })).toThrow();
    expect(() =>
      saveConfig(state, {
        ...base,
        title: "标题",
        start_at: "2026-11-01T00:00:00Z",
        end_at: "2026-12-01T00:00:00Z",
      }),
    ).not.toThrow();
    expect(() =>
      saveConfig(state, {
        ...base,
        title: "标题",
        start_at: "2026-11-01T00:00:00Z",
        end_at: "2026-12-01T00:00:00Z",
        allowed_grades: [],
      }),
    ).toThrow();
  });

  it("活动已开始后壳字段锁定", () => {
    const state = seeded();
    expect(() =>
      saveConfig(
        state,
        {
          title: "改名",
          summary: "",
          body: "",
          start_at: EVENT.start_at,
          end_at: EVENT.end_at as string,
          ship_at: null,
          distribute_at: null,
          allowed_grades: ["g1"],
          destination_schools: [],
        },
        {},
        at("2026-11-10T00:00:00Z"),
      ),
    ).toThrow(/锁定/);
  });

  it("条码：夹到区间、按 500 递增、累计不超上限，覆盖重建受占用保护", () => {
    const state = seeded();
    expect(generateBarcodes(state, 100).generated).toBe(1500);
    expect(() => generateBarcodes(state, 10000)).toThrow(/累计/);
    // 上限夹取：全新活动一次要 999999 → 只给 10000
    const fresh = seeded();
    expect(generateBarcodes(fresh, 999999).total).toBe(10000);
    expect(barcodeSummary(fresh).total).toBe(10000);
    state.barcodes[0].registration_id = 1;
    expect(() => generateBarcodes(state, 1500, true)).toThrow(/占用/);
    state.barcodes[0].registration_id = null;
    expect(generateBarcodes(state, 1500, true)).toEqual({ generated: 1500, total: 1500, replaced: true });
  });

  it("开启新一届：归档旧活动、清空条码与登记、复制年级", () => {
    const state = seeded();
    generateBarcodes(state, 1500);
    const r = newSeason(state);
    expect(state.event?.id).toBe(r.event_id);
    expect(state.event?.status).toBe("draft");
    expect(state.barcodes).toHaveLength(0);
    expect(state.config?.allowed_grades).toEqual(["g1"]);
  });

  it("审计与统计都从内存数据推导", () => {
    const state = seeded();
    expect(statsOf(state).items.total).toBe(0);
    expect(state.audit.map((a) => a.action)).toContain("config_save");
    pushAudit(state, "demo", "x", { a: 1 });
    expect(state.audit.at(-1)?.user).toBe("模拟环境");
    state.registrations.push({
      id: 99,
      reg_code: "123456",
      sender_name: "张三",
      grade: "g1",
      class_no: 3,
      dest_region: "浦东新区",
      dest_school: "建平中学",
      status: "registered",
      created_at: "2026-11-09T08:00:00.000Z",
      items: [
        {
          id: 100,
          barcode: "1234567",
          status: "registered",
          review_state: "none",
          ai_verdict: null,
          photos: [],
        },
      ],
    });
    expect(statsOf(state).items.total).toBe(1);
    expect(statsOf(state).destination_schools).toBe(1);
    expect(updateRegistration(state, 99, { status: "reported" }).reg_code).toBe("123456");
    expect(state.registrations[0].items[0].status).toBe("reported");
  });
});

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    crc ^= bytes[i];
    for (let k = 0; k < 8; k += 1) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  }
  return (crc ^ 0xffffffff) >>> 0;
}

describe("模拟环境 · 文件生成", () => {
  it("PDF 是结构完整的文本 PDF", () => {
    const bytes = buildPdf([["POSTCARD BARCODES", "1234567 7654321"]]);
    const text = new TextDecoder("latin1").decode(bytes);
    expect(text.startsWith("%PDF-1.4")).toBe(true);
    expect(text.trimEnd().endsWith("%%EOF")).toBe(true);
    expect(text).toContain("/Type /Catalog");
    const match = /startxref\n(\d+)\n%%EOF/.exec(text);
    expect(match).not.toBeNull();
    // startxref 必须真的指向 xref 表
    const offset = Number(match?.[1]);
    expect(text.slice(offset, offset + 4)).toBe("xref");
  });

  it("xlsx 是 store-only ZIP：5 个部件齐全且每个 CRC 都对得上", () => {
    const bytes = buildXlsx([["条码", "寄出人"], ["1234567", "张三"]]);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    expect(view.getUint32(0, true)).toBe(0x04034b50);

    const eocd = bytes.length - 22;
    expect(view.getUint32(eocd, true)).toBe(0x06054b50);
    const count = view.getUint16(eocd + 10, true);
    const cdOffset = view.getUint32(eocd + 16, true);
    expect(count).toBe(5);

    const names: string[] = [];
    let pos = cdOffset;
    for (let i = 0; i < count; i += 1) {
      expect(view.getUint32(pos, true)).toBe(0x02014b50);
      const crc = view.getUint32(pos + 16, true);
      const size = view.getUint32(pos + 24, true);
      const nameLen = view.getUint16(pos + 28, true);
      const localOffset = view.getUint32(pos + 42, true);
      names.push(new TextDecoder().decode(bytes.subarray(pos + 46, pos + 46 + nameLen)));

      const localNameLen = view.getUint16(localOffset + 26, true);
      const dataStart = localOffset + 30 + localNameLen;
      expect(crc32(bytes.subarray(dataStart, dataStart + size))).toBe(crc);
      pos += 46 + nameLen;
    }
    expect(names).toContain("xl/worksheets/sheet1.xml");
    expect(names).toContain("[Content_Types].xml");
  });

  it("data URL 可直接下载，文件名带模拟标记", () => {
    const url = bytesToDataUrl(buildPdf([["x"]]), "application/pdf");
    expect(url.startsWith("data:application/pdf;base64,")).toBe(true);
    expect(withSimFileSuffix("明信片登记-2026-11-08.xlsx")).toBe(
      "明信片登记-2026-11-08-仅限模拟环境使用.xlsx",
    );
  });
});

describe("模拟环境 · 路由与入口", () => {
  it("isSimRoute 只认 ?sim=1", () => {
    expect(isSimRoute("#/postcard/admin?sim=1")).toBe(true);
    expect(isSimRoute("#/postcard/admin?sim=0")).toBe(false);
    expect(isSimRoute("#/postcard/admin")).toBe(false);
    expect(isSimRoute("#/reviews?kind=postcard")).toBe(false);
  });

  it("「模拟活动」在「去审核台复核」之后，点击弹「是否进入模拟操作」", () => {
    window.location.hash = "#/postcard/admin";
    render(<PostcardAdminPage />);
    const labels = [...screen.getAllByRole("link"), ...screen.getAllByRole("button")].map(
      (el) => el.textContent,
    );
    expect(labels.indexOf("去审核台复核")).toBeLessThan(labels.indexOf("模拟活动"));
    expect(isPostcardAdminSim()).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "模拟活动" }));
    expect(screen.getByText("是否进入模拟操作")).toBeInTheDocument();
  });

  it("模拟路由渲染红底白字徽标，并挂上内存沙箱；卸载即卸下", () => {
    window.location.hash = "#/postcard/admin?sim=1";
    const { unmount } = render(<PostcardAdminPage />);
    expect(screen.getByText("模拟环境")).toHaveClass("pa-sim-badge");
    expect(screen.getByRole("button", { name: "退出模拟" })).toBeInTheDocument();
    expect(isPostcardAdminSim()).toBe(true);
    unmount();
    expect(isPostcardAdminSim()).toBe(false);
  });
});
