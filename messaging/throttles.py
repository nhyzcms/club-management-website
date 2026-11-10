"""消息 / 评论 / 私信限流（审计 M-3）。

评论与私信此前无任何服务端配额：登录用户可无限发、无限触发通知。
按用户计数；匿名请求（评论列表）不受影响。
"""
from rest_framework.throttling import SimpleRateThrottle


class _UserScopedThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view=None):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False) or not user.pk:
            return None
        return self.cache_format % {"scope": self.scope, "ident": f"u{user.pk}"}


class CommentCreateThrottle(_UserScopedThrottle):
    """评论：每用户每分钟 30 条。"""

    scope = "comment_create"
    rate = "30/min"


class MessageSendThrottle(_UserScopedThrottle):
    """私信：每用户每分钟 60 条（每条会给对方发通知）。"""

    scope = "message_send"
    rate = "60/min"


class StartPrivateThrottle(_UserScopedThrottle):
    """发起新私信：每用户每小时 20 次（会创建会话 + 通知）。"""

    scope = "start_private"
    rate = "20/hour"
