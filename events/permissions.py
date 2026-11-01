"""活动访问控制（遵循 ADR 0005：命名 BasePermission 子类 + has_perm，绝不查组名）。

身份门禁（已认证成员）由 accounts.IsVerified 在视图层单独挂——此处只管
「角色能力 + 对象所有权」。「此刻能否改 / 能否发布」由 lifecycle 守卫在
动作里收口。
"""
from rest_framework import permissions


class CanViewEvent(permissions.BasePermission):
    """查看活动：可见性由 queryset 收口；此处只要求登录（公开受众在 queryset 放行游客）。"""

    def has_permission(self, request, view):  # type: ignore[override]
        return True


class CanCreateEvent(permissions.BasePermission):
    """创建活动：登录即可（是否已认证由 IsVerified 把关）。"""

    def has_permission(self, request, view):  # type: ignore[override]
        return bool(request.user and request.user.is_authenticated)


class CanModifyEvent(permissions.BasePermission):
    """编辑 / 删除 / 发布 / 归档：组织者，或持 ``events.manage_events`` 权限者。"""

    def has_permission(self, request, view):  # type: ignore[override]
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):  # type: ignore[override]
        return (
            obj.organizer_id == request.user.pk
            or request.user.has_perm("events.manage_events")
        )
