import { afterEach, describe, expect, it, vi } from "vitest";
import { getDeviceId } from "../deviceId";

describe("getDeviceId", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("首次生成 UUID 并持久化，后续返回同一值", () => {
    const id1 = getDeviceId();
    expect(id1).toMatch(/^[0-9a-f-]{36}$/i);
    expect(localStorage.getItem("device_id")).toBe(id1);
    expect(getDeviceId()).toBe(id1);
  });

  it("localStorage 不可用时仍返回 UUID（不抛错）", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const id = getDeviceId();
    expect(typeof id).toBe("string");
    expect(id.length).toBeGreaterThan(10);
  });
});
