from rest_framework import permissions

from reviews.discipline import is_muted

from .models import Comment, CommentThread
from .services import can_manage_thread


class IsConversationParticipant(permissions.BasePermission):
    """只有对话参与者可以查看/发送消息。"""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if hasattr(obj, "participants"):
            return obj.participants.filter(pk=user.pk).exists()
        if hasattr(obj, "conversation"):
            return obj.conversation.participants.filter(pk=user.pk).exists()
        return False


class IsNotMuted(permissions.BasePermission):
    """全站禁言：不能发评论 / 私信（仍可登录、阅读、接收）。"""

    message = "你已被全站禁言，暂时不能发言。"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return not is_muted(user)


class CanManageThread(permissions.BasePermission):
    """改评论区状态 / 墓碑删除评论：主人或 ``manage_comment_thread``。不随管理新闻等继承。"""

    message = "没有管理该评论区的权限。"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, CommentThread):
            thread = obj
        elif isinstance(obj, Comment):
            thread = obj.thread
        else:
            thread = getattr(obj, "thread", None)
        if thread is None:
            return False
        return can_manage_thread(request.user, thread)


class CanMuteUser(permissions.BasePermission):
    """全站禁言 / 解除：持 ``reviews.mute_user``。"""

    message = "没有全站禁言权限。"

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("reviews.mute_user"))
