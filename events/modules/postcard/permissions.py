"""明信片互寄访问控制（ADR 0005：命名 BasePermission + has_perm，绝不查组名）。

两个命名工作流权限声明在 ``PostcardConfig.Meta.permissions``：

- ``events.manage_postcard``：配置 / 条码 / 记录管理 / 导出 / 统计 / 审计查看；
- ``events.review_postcard``：复核台 + 签收（持有者可能与管理者不同——
  比如检录志愿者只签收不碰配置，这正是拆两个权限的触发条件）。

``is_superuser`` 是唯一逃生舱（全站硬规则）。公开端点不挂权限类，靠
phase 门禁 + 限流 + Turnstile 收口。
"""
from rest_framework import permissions


class CanManagePostcard(permissions.BasePermission):
    """管理明信片互寄：持 ``events.manage_postcard``。"""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        return bool(
            user and user.is_authenticated and (
                user.is_superuser or user.has_perm("events.manage_postcard")
            )
        )


class CanReviewPostcard(permissions.BasePermission):
    """复核 / 签收：持 ``events.review_postcard`` 或 ``manage_postcard``（管理含复核）。"""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        return bool(
            user and user.is_authenticated and (
                user.is_superuser
                or user.has_perm("events.review_postcard")
                or user.has_perm("events.manage_postcard")
            )
        )
