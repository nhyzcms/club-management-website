from rest_framework import permissions


class CanModerateReview(permissions.BasePermission):
    """审核队列读写：持 reviews.moderate。"""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("reviews.moderate"))


class CanViewFeedback(permissions.BasePermission):
    """意见反馈列表 / 了结：持 reviews.read_feedback。"""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("reviews.read_feedback"))


class CanAccessFeedback(permissions.BasePermission):
    """意见反馈详情：署名创建人或持 reviews.read_feedback。"""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if obj.creator_id == request.user.pk:
            return True
        return request.user.has_perm("reviews.read_feedback")


class CanHandleReport(permissions.BasePermission):
    """举报案列表 / 详情 / 驳回 / 成立：持 reviews.handle_report。"""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("reviews.handle_report"))
