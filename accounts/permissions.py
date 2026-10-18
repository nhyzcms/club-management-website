from rest_framework import permissions

from .models import is_verified


class IsVerified(permissions.BasePermission):
    """写操作门槛（ADR-0006）：已登录且账号已认证（任一认证通道 approved）才放行。

    取代旧的 ``IsIdentityVerified``（读 profile.identity_verified）——认证态单一事实源是
    ``is_verified``（任一通道 approved）。作用域不变：只挂到对外可见的**写**动作（建任务 /
    发消息 / 建申报 / 投票 等）的 permission_classes，不挂读动作——故此处不做 SAFE_METHODS
    旁路（粒度由各 ViewSet 的 get_permissions 控制）。

    认证轴不特判超管（ADR-0013）：委任走 appointment 通道，本门禁只读 ``is_verified``。
    ``is_superuser`` 仍是权限轴逃生舱（``has_perm`` 恒真，ADR-0005 决策 9），不在这里。
    """

    message = "请先完成账号认证后再使用此功能（发帖 / 发消息 / 建申报等）。"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return is_verified(user)


class CanReviewIdentity(permissions.BasePermission):
    """身份审核队列读写：持 accounts.can_review_identity。"""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.has_perm("accounts.can_review_identity")
        )
