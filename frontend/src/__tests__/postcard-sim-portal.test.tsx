import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import {
  emptySimState,
  generateBarcodes,
  lookupRegistrations,
  myRegistrations,
  portalOf,
  publish,
  requestManualReview,
  saveConfig,
  statsOf,
  submitRegistration,
  updateOwnRegistration,
  cancelOwnRegistration,
  type SimState,
} from "../postcardSim/state";
import { createSimPostcardUserApi } from "../postcardSim/apiUser";
import { createSimPostcardAdminApi } from "../postcardSim/api";
import { enterSim, exitSim, isSimActive, isSimRoute, withSimParam } from "../postcardSim/session";
import { isPostcardSim } from "../api/postcard";
import PostcardSimHost from "../postcardSim/SimHost";

/**
 * 模拟环境 · 用户端（PR2）：登记 → 历史 → 查询 → 改/取消 → 复核 → 签收的闭环。
 *
 * 全部走内存 state，不碰后端；顺带钉住「AI 未配置 → 转人工 **也立刻发码**」这条
 * 用户 2026-11-08 定的规则，以及照片「通过即删」的生命周期。
 */

const NOW = new Date("2026-11-10T00:00:00Z");

function seeded(): SimState {
  const state = emptySimState();
  saveConfig(
    state,
    {
      title: "2026 明信片互寄",
      summary: "",
      body: "<p>公告正文</p>",
      start_at: "2026-11-01T00:00:00.000Z",
      end_at: "2026-12-01T00:00:00.000Z",
      ship_at: "2026-11-20T00:00:00.000Z",
      distribute_at: null,
      allowed_grades: ["g1", "g2"],
      destination_schools: [{ region: "浦东新区", name: "建平中学", no: 1 }],
    },
    {},
    new Date("2026-10-01T00:00:00Z"),
  );
  publish(state);
  generateBarcodes(state, 1500);
  return state;
}

function submit(state: SimState, barcodes: string[], photos = 0) {
  return submitRegistration(
    state,
    {
      sender_name: "张三",
      grade: "g1",
      class_no: 3,
      dest_region: "浦东新区",
      dest_school: "建平中学",
      fingerprint: "fp-1",
      items: barcodes.map((barcode) => ({
        barcode,
        photos: Array.from({ length: photos }, (_, i) => ({
          side: i === 0 ? ("front" as const) : ("back" as const),
          data_url: `data:image/jpeg;base64,AAA${i}`,
        })),
      })),
    },
    NOW,
  );
}

afterEach(() => {
  exitSim();
  window.location.hash = "";
});

describe("模拟环境 · 用户端 portal", () => {
  it("登记中 → can_register；节点时间进进度条", () => {
    const state = seeded();
    const portal = portalOf(state, NOW);
    expect(portal.phase).toBe("registering");
    expect(portal.can_register).toBe(true);
    expect(portal.grades.map((g) => g.value)).toEqual(["g1", "g2"]);
    expect(portal.schools[0].name).toBe("建平中学");
    expect(portal.regions).toHaveLength(16);
    expect(portal.progress.map((p) => p.key)).toEqual(["start", "ship", "distribute", "end"]);
    expect(portal.progress[0].reached).toBe(true);
    expect(portal.progress[1].reached).toBe(false);
  });

  it("未配置活动 → 未开始、不可登记", () => {
    const portal = portalOf(emptySimState(), NOW);
    expect(portal.phase).toBe("not_started");
    expect(portal.can_register).toBe(false);
    expect(portal.schools).toEqual([]);
  });
});

describe("模拟环境 · 登记", () => {
  it("AI 未配置 → 转人工复核，但登记码立即发放、照片保留", () => {
    const state = seeded();
    const codes = state.barcodes.slice(0, 2).map((b) => b.code);
    const res = submit(state, codes, 2);
    expect(res.code_granted).toBe(true);
    expect(res.reg_code).toMatch(/^\d{6}$/);
    expect(res.review.state).toBe("manual_pending");
    const reg = state.registrations[0];
    expect(reg.items).toHaveLength(2);
    expect(reg.items[0].review_state).toBe("manual_pending");
    expect(reg.items[0].photos).toHaveLength(2);
    // 条码被占用
    expect(state.barcodes.filter((b) => b.registration_id !== null)).toHaveLength(2);
  });

  it("AI 配齐 → 直接通过并删除照片", () => {
    const state = seeded();
    state.ai.enabled = true;
    state.ai.base_url = "https://ai.example.com/v1";
    state.ai.model = "gpt-4o-mini";
    state.ai.api_key_set = true;
    const res = submit(state, [state.barcodes[0].code], 2);
    expect(res.review.state).toBe("approved");
    expect(state.registrations[0].items[0].photos).toHaveLength(0);
  });

  it("条码不存在 / 已被占用 / 年级不在范围 都会被拒", () => {
    const state = seeded();
    expect(() => submit(state, ["0000000"])).toThrow(/不在本次活动/);
    const code = state.barcodes[0].code;
    submit(state, [code]);
    expect(() => submit(state, [code])).toThrow(/已被登记/);
    expect(() =>
      submitRegistration(state, {
        sender_name: "李四",
        grade: "g3",
        class_no: 1,
        dest_region: "浦东新区",
        dest_school: "建平中学",
        fingerprint: "fp-2",
        items: [{ barcode: state.barcodes[1].code, photos: [] }],
      }),
    ).toThrow(/年级/);
  });
});

describe("模拟环境 · 历史 / 查询 / 改 / 取消", () => {
  it("历史按指纹归属；查询码给完整信息、姓名给掩码", () => {
    const state = seeded();
    const res = submit(state, [state.barcodes[0].code]);
    expect(myRegistrations(state, "fp-1")).toHaveLength(1);
    expect(myRegistrations(state, "fp-other")).toHaveLength(0);

    const regCode = res.reg_code as string;
    const byCode = lookupRegistrations(state, regCode);
    expect(byCode.kind).toBe("code");
    expect(byCode.results[0].reg_code).toBe(regCode);

    const byName = lookupRegistrations(state, "张三");
    expect(byName.kind).toBe("name");
    expect(byName.results[0].reg_code).toBe(`${regCode.slice(0, 2)}****`);
    expect(byName.results[0].items[0].photos).toEqual([]);
  });

  it("改寄出人信息 / 取消单份与整批", () => {
    const state = seeded();
    const codes = state.barcodes.slice(0, 2).map((b) => b.code);
    const res = submit(state, codes);
    const reg = state.registrations[0];

    const regCode = res.reg_code as string;
    const updated = updateOwnRegistration(state, regCode, { sender_name: "王五", class_no: 5 }, NOW);
    expect(updated.sender_name).toBe("王五");
    expect(updated.class_no).toBe(5);

    const one = cancelOwnRegistration(state, regCode, "one", reg.items[0].id, NOW);
    expect(one.items[0].status).toBe("cancelled");
    expect(one.items[1].status).toBe("registered");
    expect(one.status).toBe("registered");

    const all = cancelOwnRegistration(state, regCode, "all", undefined, NOW);
    expect(all.status).toBe("cancelled");
    expect(all.items.every((it) => it.status === "cancelled")).toBe(true);
  });

  it("申请人工复核：把 ai_failed 拉回 manual_pending", () => {
    const state = seeded();
    const res = submit(state, [state.barcodes[0].code]);
    state.registrations[0].items[0].review_state = "ai_failed";
    const out = requestManualReview(state, { regCode: res.reg_code as string }, NOW);
    expect(out.count).toBe(1);
    expect(state.registrations[0].items[0].review_state).toBe("manual_pending");
  });
});

describe("模拟环境 · 三端联动（登记 → 审核台 → 签收 → 统计）", () => {
  it("审核台通过后照片清空，签收置已报寄，统计跟着变", async () => {
    const state = seeded();
    const admin = createSimPostcardAdminApi(state);
    const user = createSimPostcardUserApi(state);

    const res = await user.register(
      (() => {
        const fd = new FormData();
        fd.set("sender_name", "张三");
        fd.set("grade", "g1");
        fd.set("class_no", "3");
        fd.set("dest_region", "浦东新区");
        fd.set("dest_school", "建平中学");
        fd.set("fingerprint", "fp-1");
        fd.set("items", JSON.stringify([{ barcode: state.barcodes[0].code }]));
        return fd;
      })(),
    );
    expect(res.code_granted).toBe(true);

    const queue = await admin.reviewQueue(1, "manual_pending");
    expect(queue.count).toBe(1);
    const row = queue.results[0];
    expect(row.barcode).toBe(state.barcodes[0].code);

    await admin.reviewDecision(row.item_id, "pass", "看起来没问题");
    expect((await admin.reviewQueue(1, "manual_pending")).count).toBe(0);

    const receipt = await admin.lookup(row.barcode);
    expect(receipt.registration.sender_name).toBe("张三");
    await admin.confirm(row.barcode);
    expect((await admin.lookup(row.barcode)).item_status).toBe("reported");

    expect(statsOf(state).items.reported).toBe(1);
    expect(statsOf(state).destination_schools).toBe(1);
  });

  it("查询不存在的条码 → 明信片未登记", async () => {
    const admin = createSimPostcardAdminApi(seeded());
    await expect(admin.lookup("0000000")).rejects.toThrow(/未登记/);
  });
});

describe("模拟环境 · 路由与安装", () => {
  it("withSimParam 会给任意路由补参数", () => {
    expect(withSimParam("#/postcard")).toBe("#/postcard?sim=1");
    expect(withSimParam("#/reviews?kind=postcard")).toBe("#/reviews?kind=postcard&sim=1");
    expect(withSimParam("#/postcard?sim=1")).toBe("#/postcard?sim=1");
    expect(isSimRoute("#/postcard/receive?sim=1")).toBe(true);
  });

  it("进入/退出同时装卸用户端与管理端两套实现", () => {
    enterSim();
    expect(isPostcardSim()).toBe(true);
    expect(isSimActive()).toBe(true);
    exitSim();
    expect(isPostcardSim()).toBe(false);
    expect(isSimActive()).toBe(false);
  });

  it("用户页 ↔ 管理端来回切不丢沙箱；离开明信片这条链才清空", async () => {
    const { isSimActive } = await import("../postcardSim/session");
    window.location.hash = "#/postcard?sim=1";
    render(<PostcardSimHost />);
    expect(isSimActive()).toBe(true);

    // 切到管理端（URL 没带 sim=1 也一样）：沙箱保留
    window.location.hash = "#/postcard/admin";
    await waitFor(() => expect(isSimActive()).toBe(true));
    // 回用户页
    window.location.hash = "#/postcard/receive";
    await waitFor(() => expect(isSimActive()).toBe(true));
    // 离开这条链 → 清空
    window.location.hash = "#/news";
    await waitFor(() => expect(isSimActive()).toBe(false));
  });

  it("非管理端的模拟页显示红底白字浮标；管理端不重复显示", () => {
    window.location.hash = "#/postcard?sim=1";
    const first = render(<PostcardSimHost />);
    expect(screen.getByText("模拟环境")).toHaveClass("pc-sim-dock-badge");
    first.unmount();

    window.location.hash = "#/postcard/admin?sim=1";
    const second = render(<PostcardSimHost />);
    expect(screen.queryByText("模拟环境")).toBeNull();
    second.unmount();
  });
});
