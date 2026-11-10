"""活动访问控制（遵循 ADR 0005：命名 BasePermission 子类 + has_perm，绝不查组名）。

身份门禁（已认证成员）由 accounts.IsVerified 在视图层单独挂——此处只管"角色能力 +
对象所有权"。读：已登录成员见全部过审活动；访客仅 list/retrieve 公开调研（AllowAny + queryset）。
"""
from rest_framework import permissions


class CanViewActivity(permissions.BasePermission):
    """查看活动：所有登录成员可见（活动对内公开）。"""

    def has_permission(self, request, view): # type: ignore
        return bool(request.user and request.user.is_authenticated)


class CanCreateActivity(permissions.BasePermission):
    """创建活动：登录即可（是否已认证由 IsVerified 把关，故此处只判登录）。"""

    def has_permission(self, request, view): # type: ignore
        return bool(request.user and request.user.is_authenticated)


class CanModifyActivity(permissions.BasePermission):
    """编辑/删除活动：发起人，或持 activities.manage_activity 权限者。

    状态相关的"此刻能否改"由 lifecycle 守卫在具体动作里收口；此处只判归属与角色。
    """

    def has_permission(self, request, view): # type: ignore
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return obj.creator_id == request.user.pk or request.user.has_perm("activities.manage_activity")


class CanReviewSubmission(permissions.BasePermission):
    """复审征集作品：活动发起人，或持 activities.review_collection 权限者（对象级）。

    「此刻能否复审」（征集须在 collecting / reviewing 阶段、滚动复审）由 review_submission
    动作在调用前校验；此处只判归属与角色。
    """

    def has_permission(self, request, view): # type: ignore
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return obj.creator_id == request.user.pk or request.user.has_perm("activities.review_collection")
