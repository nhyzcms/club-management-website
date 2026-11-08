import { describe, expect, it } from "vitest";
import {
  addBarcode,
  buildRegisterFormData,
  checkPhotoFile,
  failedReviewRegCodes,
  hasAiFailedItem,
  needsReviewPoll,
  reviewOutcomeOf,
  schoolsInRegion,
  validateRegistration,
  type DraftItem,
  type RegisterFormValues,
} from "../components/postcard/pure";
import type { PostcardItemSummary, PostcardRegistrationSummary, PostcardSchool } from "../api/postcard";

const SCHOOLS: PostcardSchool[] = [
  { region: "浦东新区", name: "友爱中学" },
  { region: "浦东新区", name: "临港一中" },
  { region: "黄浦区", name: "光明中学" },
];

const VALID_VALUES: RegisterFormValues = {
  sender_name: "张三",
  grade: "g1",
  class_no: "3",
  dest_region: "浦东新区",
  dest_school: "友爱中学",
};

function item(barcode: string): DraftItem {
  return { barcode, front: new File(["f"], "f.jpg", { type: "image/jpeg" }), back: new File(["b"], "b.jpg", { type: "image/jpeg" }) };
}

describe("addBarcode（扫码/手填入列三道闸）", () => {
  it("7 位数字入列", () => {
    const r = addBarcode([], "1234567");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.items[0].barcode).toBe("1234567");
  });

  it("容错空白与连字符", () => {
    const r = addBarcode([], " 123-4567 ");
    expect(r.ok).toBe(true);
  });

  it("非 7 位数字拒绝", () => {
    expect(addBarcode([], "123456").ok).toBe(false);
    expect(addBarcode([], "12345678").ok).toBe(false);
    expect(addBarcode([], "12345a7").ok).toBe(false);
    expect(addBarcode([], "").ok).toBe(false);
  });

  it("重复条码拒绝（一条码一明信片）", () => {
    const r = addBarcode([item("1234567")], "1234567");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toContain("已在列表中");
  });

  it("超过 5 张拒绝", () => {
    const five = ["1", "2", "3", "4", "5"].map((n) => item(`123456${n}`));
    const r = addBarcode(five, "7654321");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toContain("5 张");
  });
});

describe("schoolsInRegion（寄达校按区过滤）", () => {
  it("只留所选区，保持配置顺序", () => {
    expect(schoolsInRegion(SCHOOLS, "浦东新区")).toEqual(["友爱中学", "临港一中"]);
    expect(schoolsInRegion(SCHOOLS, "黄浦区")).toEqual(["光明中学"]);
    expect(schoolsInRegion(SCHOOLS, "崇明区")).toEqual([]);
  });
});

describe("validateRegistration（提交前整单校验）", () => {
  it("全过返回 null", () => {
    expect(validateRegistration(VALID_VALUES, [item("1234567")])).toBeNull();
  });

  it("逐项缺漏给出可读文案", () => {
    expect(validateRegistration({ ...VALID_VALUES, sender_name: " " }, [item("1234567")])).toContain("姓名");
    expect(validateRegistration({ ...VALID_VALUES, grade: "" }, [item("1234567")])).toContain("年级");
    expect(validateRegistration({ ...VALID_VALUES, dest_school: "" }, [item("1234567")])).toContain("寄达校");
    expect(validateRegistration(VALID_VALUES, [])).toContain("至少");
  });

  it("照片缺一面按张序提示", () => {
    const noBack = { barcode: "1234567", front: item("1234567").front, back: null };
    expect(validateRegistration(VALID_VALUES, [noBack])).toContain("反面照片");
  });
});

describe("buildRegisterFormData（multipart 契约）", () => {
  it("字段、items JSON、照片键名与后端 RegisterView 对齐", () => {
    const fd = buildRegisterFormData(VALID_VALUES, [item("1234567"), item("7654321")], "aabbccdd11223344", "tok-1");
    expect(fd.get("sender_name")).toBe("张三");
    expect(fd.get("grade")).toBe("g1");
    expect(fd.get("class_no")).toBe("3");
    expect(fd.get("dest_region")).toBe("浦东新区");
    expect(fd.get("dest_school")).toBe("友爱中学");
    expect(JSON.parse(fd.get("items") as string)).toEqual([
      { barcode: "1234567" }, { barcode: "7654321" },
    ]);
    expect(fd.get("fingerprint")).toBe("aabbccdd11223344");
    expect(fd.get("turnstile_token")).toBe("tok-1");
    expect(fd.get("photo_0_front")).toBeInstanceOf(File);
    expect(fd.get("photo_0_back")).toBeInstanceOf(File);
    expect(fd.get("photo_1_front")).toBeInstanceOf(File);
    expect(fd.get("photo_1_back")).toBeInstanceOf(File);
  });

  it("无 token 时不带 turnstile_token 键", () => {
    const fd = buildRegisterFormData(VALID_VALUES, [item("1234567")], "aabbccdd11223344", "");
    expect(fd.get("turnstile_token")).toBeNull();
  });
});

describe("checkPhotoFile（照片预检）", () => {
  it("图片类型 + ≤5MB 通过", () => {
    expect(checkPhotoFile(new File(["x"], "a.jpg", { type: "image/jpeg" }))).toBeNull();
  });
  it("非图片与超大小拒绝", () => {
    expect(checkPhotoFile(new File(["x"], "a.pdf", { type: "application/pdf" }))).toContain("图片");
    const big = new File(["x"], "a.jpg", { type: "image/jpeg" });
    Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
    expect(checkPhotoFile(big)).toContain("5MB");
  });
});

function reg(overrides: Partial<PostcardRegistrationSummary> = {}): PostcardRegistrationSummary {
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
    items: [],
    ...overrides,
  };
}

describe("轮询与 sendBeacon 清理的判定", () => {
  it("有待审条目才轮询", () => {
    expect(needsReviewPoll([reg({ items: [{ id: 1, barcode: "1234567", status: "registered", status_label: "已登记", review_state: "pending", review_label: "待审核", mismatched: [], comment: "", photos: [] }] })])).toBe(true);
    expect(needsReviewPoll([reg({ items: [{ id: 1, barcode: "1234567", status: "registered", status_label: "已登记", review_state: "ai_passed", review_label: "AI 通过", mismatched: [], comment: "", photos: [] }] })])).toBe(false);
    expect(needsReviewPoll([])).toBe(false);
  });

  it("终态失败（ai_failed / manual_failed）的登记码才进清理清单；已取消的不进", () => {
    const mk = (state: string, status = "registered") =>
      reg({
        reg_code: state.slice(0, 6).padEnd(6, "0"),
        status,
        items: [{ id: 1, barcode: "1234567", status: "registered", status_label: "已登记", review_state: state, review_label: state, mismatched: [], comment: "", photos: [] }],
      });
    const regs = [mk("ai_failed"), mk("manual_failed"), mk("ai_passed"), mk("ai_failed", "cancelled")];
    expect(failedReviewRegCodes(regs)).toEqual(["ai_fai", "manual"]);
  });

  it("hasAiFailedItem 决定「申请人工复核」按钮", () => {
    const withFailed = reg({ items: [{ id: 1, barcode: "1234567", status: "registered", status_label: "已登记", review_state: "ai_failed", review_label: "AI 不匹配", mismatched: ["寄达校"], comment: "", photos: [] }] });
    expect(hasAiFailedItem(withFailed)).toBe(true);
    expect(hasAiFailedItem(reg())).toBe(false);
  });
});

describe("reviewOutcomeOf（登记码发放规则，2026-11-08 用户指定）", () => {
  const it_ = (state: string | null, extra: Partial<PostcardItemSummary> = {}): PostcardItemSummary => ({
    id: 1, barcode: "1234567", status: "registered", status_label: "已登记",
    review_state: state, review_label: state, mismatched: [], comment: "", photos: [], ...extra,
  });
  const withItems = (...items: PostcardItemSummary[]) => reg({ items });

  it("全部 AI 通过 → 发码（via ai）", () => {
    expect(reviewOutcomeOf(withItems(it_("ai_passed"), it_("ai_passed")))).toEqual({ kind: "granted", via: "ai" });
  });

  it("转人工（manual_pending）→ 立即发码（via manual）", () => {
    expect(reviewOutcomeOf(withItems(it_("manual_pending")))).toEqual({ kind: "granted", via: "manual" });
  });

  it("AI 通过 + 转人工混合 → 发码（via manual，还有待人工的）", () => {
    expect(reviewOutcomeOf(withItems(it_("ai_passed"), it_("manual_pending")))).toEqual({ kind: "granted", via: "manual" });
  });

  it("AI 判不匹配 → 不发码，带错项与说明", () => {
    const out = reviewOutcomeOf(withItems(
      it_("ai_failed", { mismatched: ["寄达校"], comment: "学校名不符" }),
      it_("ai_passed"),
    ));
    expect(out).toEqual({ kind: "rejected", mismatched: ["寄达校"], comment: "学校名不符" });
  });

  it("人工复核不通过（manual_failed）→ 同样是终态失败，不发码", () => {
    expect(reviewOutcomeOf(withItems(it_("manual_failed", { mismatched: ["寄出人姓名"] })))).toEqual({
      kind: "rejected", mismatched: ["寄出人姓名"], comment: "",
    });
  });

  it("仍有 pending → 继续等（不亮码也不判失败）", () => {
    expect(reviewOutcomeOf(withItems(it_("pending")))).toEqual({ kind: "pending" });
    expect(reviewOutcomeOf(withItems(it_("pending"), it_("ai_passed")))).toEqual({ kind: "pending" });
    expect(reviewOutcomeOf(reg())).toEqual({ kind: "pending" });
  });
});
