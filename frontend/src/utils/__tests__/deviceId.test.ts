import { afterEach, describe, expect, it, vi } from "vitest";
import { createDeviceId, getDeviceId } from "../deviceId";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("getDeviceId", () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
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

  it("非安全上下文没有 crypto.randomUUID 时用 getRandomValues 生成 v4 UUID", () => {
    // 公网 HTTP 的 test 环境：crypto.randomUUID 不存在，getRandomValues 仍在。
    vi.stubGlobal("crypto", {
      getRandomValues: (arr: Uint8Array) => {
        for (let i = 0; i < arr.length; i += 1) arr[i] = i;
        return arr;
      },
    });

    expect(createDeviceId()).toMatch(UUID_V4);
  });

  it("连 crypto 都没有时仍能生成（Math.random 兜底）", () => {
    vi.stubGlobal("crypto", undefined);

    expect(createDeviceId()).toMatch(UUID_V4);
  });
});
