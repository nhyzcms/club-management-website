import { describe, expect, it } from "vitest";
import { formatExpiry, formatRemaining } from "../validity";

describe("validity 展示口径", () => {
  it("永久 / 到期时间的格式化", () => {
    expect(formatExpiry(null)).toBe("永久有效");
    expect(formatExpiry("2027-01-02T03:04:00+00:00")).toMatch(/^2027-01-0[12] \d{2}:04$/);
  });

  it("剩余天数：正数 / 不足一天 / 已到期 / 永久", () => {
    expect(formatRemaining(365, "2027-10-18T00:00:00+00:00")).toBe("365 天");
    expect(formatRemaining(null, null)).toBe("永久有效");

    const soon = new Date(Date.now() + 3 * 3600_000).toISOString();
    expect(formatRemaining(0, soon)).toBe("不足 1 天");

    const past = new Date(Date.now() - 3600_000).toISOString();
    expect(formatRemaining(0, past)).toBe("已到期");
    expect(formatRemaining(-3, past)).toBe("已到期");
  });
});
