import { describe, expect, it } from "vitest";
import { evaluateShellVersion, parseShellVersion } from "../shellVersion";

const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
  + "(KHTML, like Gecko) Version/4.0 Chrome/125.0.0.0 Mobile Safari/537.36";

const shellUa = (name: string, code?: number) => {
  const marker = code === undefined
    ? `NhyzClubApp/${name}`
    : `NhyzClubApp/${name} (Android; ${code})`;
  return `${ANDROID} ${marker} NhyzClubShell/${name} (native; ${code ?? 0})`;
};

describe("parseShellVersion", () => {
  it("解析壳版本名与版本码", () => {
    expect(parseShellVersion(shellUa("0.2.0", 2))).toEqual({ versionName: "0.2.0", versionCode: 2 });
  });

  it("缺 (Android; N) 时版本码为 null，不当成 0", () => {
    expect(parseShellVersion(shellUa("0.2.0"))).toEqual({ versionName: "0.2.0", versionCode: null });
  });

  it("带连字符/多位版本码也能解析", () => {
    expect(parseShellVersion(shellUa("1.10.0-rc1", 1100))).toEqual({
      versionName: "1.10.0-rc1",
      versionCode: 1100,
    });
  });

  it("浏览器 UA（含手机浏览器）返回 null", () => {
    expect(parseShellVersion(ANDROID)).toBeNull();
    expect(parseShellVersion("")).toBeNull();
  });
});

describe("evaluateShellVersion", () => {
  it("浏览器不受闸门约束", () => {
    expect(evaluateShellVersion(ANDROID)).toBe("ok");
    expect(evaluateShellVersion("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0")).toBe("ok");
  });

  it("壳版本码低于最低要求 → outdated", () => {
    expect(evaluateShellVersion(shellUa("0.1.0", 1))).toBe("outdated");
    expect(evaluateShellVersion(shellUa("0.1.0", 1), 2)).toBe("outdated");
  });

  it("等于或高于最低要求 → ok", () => {
    expect(evaluateShellVersion(shellUa("0.2.0", 2))).toBe("ok");
    expect(evaluateShellVersion(shellUa("0.3.0", 3))).toBe("ok");
  });

  it("解析不出版本码 → unknown（放行，不锁死用户）", () => {
    expect(evaluateShellVersion(shellUa("0.2.0"))).toBe("unknown");
  });
});
