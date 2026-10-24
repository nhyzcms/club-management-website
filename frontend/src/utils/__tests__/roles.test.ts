import { describe, expect, it } from "vitest";
import { ADMIN_ROLE_VARIANTS, canAccessAdmin } from "../roles";

describe("canAccessAdmin（后台入口可见性）", () => {
  it("admin / superadmin 命中（对应后端 is_staff）", () => {
    expect(canAccessAdmin("admin")).toBe(true);
    expect(canAccessAdmin("superadmin")).toBe(true);
  });

  it("user / visitor 不命中", () => {
    expect(canAccessAdmin("user")).toBe(false);
    expect(canAccessAdmin("visitor")).toBe(false);
  });

  it("空值 / 未知值一律视为无权限（失败即关闭）", () => {
    expect(canAccessAdmin("")).toBe(false);
    expect(canAccessAdmin(undefined)).toBe(false);
    expect(canAccessAdmin(null)).toBe(false);
    expect(canAccessAdmin("Admin")).toBe(false);
    expect(canAccessAdmin("staff")).toBe(false);
    expect(canAccessAdmin(" admin")).toBe(false);
  });

  it("白名单与后端 _role_for 的两个 staff 徽章一致", () => {
    expect([...ADMIN_ROLE_VARIANTS]).toEqual(["admin", "superadmin"]);
  });
});
