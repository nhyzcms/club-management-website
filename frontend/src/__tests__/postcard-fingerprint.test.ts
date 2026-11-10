import { beforeEach, describe, expect, it } from "vitest";
import { getPostcardFingerprint } from "../utils/fingerprint";

describe("明信片设备指纹（归属第二轨）", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("产出 8~128 位小写 hex（后端 _FINGERPRINT_RE 契约）", () => {
    const fp = getPostcardFingerprint();
    expect(fp).toMatch(/^[0-9a-f]{8,128}$/);
  });

  it("同设备稳定：重复调用结果一致", () => {
    expect(getPostcardFingerprint()).toBe(getPostcardFingerprint());
  });

  it("首次计算后持久化到 localStorage（canvas 渲染变化不丢归属）", () => {
    const fp = getPostcardFingerprint();
    expect(localStorage.getItem("cobalt:postcard-fp")).toBe(fp);
    // 清掉内存态再取：直接读缓存，不再重算
    expect(getPostcardFingerprint()).toBe(fp);
  });

  it("缓存被污染（非 hex）时重算自愈", () => {
    localStorage.setItem("cobalt:postcard-fp", "not-hex!!");
    const fp = getPostcardFingerprint();
    expect(fp).toMatch(/^[0-9a-f]{8,128}$/);
    expect(localStorage.getItem("cobalt:postcard-fp")).toBe(fp);
  });
});
