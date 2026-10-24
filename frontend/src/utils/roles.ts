/**
 * 身份 → 后台权限的派生规则。
 *
 * 单一真源在服务端：`accounts.views._role_for()` 用 `is_staff` 派生身份徽章
 * （`superadmin` / `admin` / `user` / `visitor`），而 Django admin 的门禁本身
 * 也只认 `is_staff && is_active`。因此前端「能不能进后台」只需要看 variant，
 * 不必再额外请求一次权限接口。
 */

/** 允许进入 Django 后台（/admin/）的身份徽章 variant。 */
export const ADMIN_ROLE_VARIANTS = ["admin", "superadmin"] as const;

/** 该身份徽章是否允许进入后台；未知 / 空值一律视为无权限（失败即关闭）。 */
export function canAccessAdmin(roleVariant?: string | null): boolean {
  if (!roleVariant) return false;
  return (ADMIN_ROLE_VARIANTS as readonly string[]).includes(roleVariant);
}
