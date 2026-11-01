"""通知源定义（注册即生效，见 messaging.apps.ready）。

事件表必须与业务代码实际发出的 ``event`` 字符串一一对应（订阅粒度为源级，
事件用于展示；新增事件时两处同步修改）。

``dedup_identity`` 声明「同一未读事项」的身份：同键未读通知只保留一条（去重聚合），
读掉之后下一条才重新通知；不声明 = 每条单独通知。
"""
from .registry import Event, NotificationSource, register_source

# 私信站内通知的事件名（``dm_dedup_key`` 与 DmSource 共用，避免两处格式漂移）。
DM_EVENT = "new_message"


def dm_dedup_key(conversation_id) -> str:
    """私信站内通知的未读聚合键：**每个会话一条未读通知**。

    ``dispatch`` 落库时用它聚合；``messaging.services.mark_conversation_read``
    读消息时用同一个键把该会话的未读通知一并标已读——两处必须同格式，故收在这里。
    """
    return f"dm:{DM_EVENT}:{conversation_id}"


@register_source
class ReviewSource(NotificationSource):
    key = "review"
    name = "审核系统"
    description = "内容审核、举报与意见反馈处理、身份认证"
    color = "#0756a2"
    emoji = "🛡️"
    events = (
        # —— 待办：发给有处理权限的人（权限驱动投递）——
        Event("content_submitted", "新内容送审"),
        Event("feedback_submitted", "新意见反馈"),
        Event("report_submitted", "新举报"),
        Event("identity_submitted", "新认证申请"),
        Event("password_reset_requested", "新密码重置申请"),
        # —— 结果：发给当事人 ——
        Event("approved", "内容审核通过"),
        Event("rejected", "内容审核驳回"),
        Event("removed", "内容已下架"),
        Event("closed", "意见反馈了结"),
        Event("report_resolved", "举报处理结果"),
        Event("identity_resolved", "认证审核结果"),
        Event("password_reset_resolved", "密码重置申请结果"),
    )
    default_channels = ("site",)


@register_source
class ActivitySource(NotificationSource):
    key = "activity"
    name = "互动生命周期"
    description = "互动发布、到点开放"
    color = "#e8833a"
    emoji = "📅"
    events = (
        Event("published", "互动发布"),
        Event("opened", "互动开始"),
    )
    default_channels = ("site",)


@register_source
class CommentSource(NotificationSource):
    key = "comment"
    name = "评论回复"
    description = "有人回复了你的评论或提到了你"
    color = "#2e9e6b"
    emoji = "💬"
    events = (
        Event("comment_replied", "评论回复"),
        Event("comment_mentioned", "@ 提及"),
    )
    default_channels = ("site",)


@register_source
class DmSource(NotificationSource):
    key = "dm"
    name = "私信"
    description = "收到新私信（按会话聚合，站内提示不复制内容）"
    color = "#7c5cd6"
    emoji = "✉️"
    events = (Event(DM_EVENT, "新私信"),)
    default_channels = ("site",)

    def dedup_identity(self, event: str, payload) -> str | None:
        """同一会话的未读私信通知合成一条（键 = ``dm:new_message:<会话 id>``）。"""
        conversation_id = payload.get("id")
        return str(conversation_id) if conversation_id else None


@register_source
class AnnouncementSource(NotificationSource):
    key = "announcement"
    name = "全站公告"
    description = "全站弹窗公告（可在通知里回看）"
    color = "#d99a1f"
    emoji = "📢"
    events = (Event("published", "公告发布"),)
    default_channels = ("site",)


@register_source
class DisciplineSource(NotificationSource):
    key = "discipline"
    name = "纪律 / 处罚"
    description = "禁言生效、解除等纪律通知"
    color = "#d64545"
    emoji = "⚖️"
    events = (
        Event("muted", "禁言生效"),
        Event("mute_lifted", "禁言解除"),
        Event("mute_expired", "禁言到期"),
    )
    default_channels = ("site",)


@register_source
class ValiditySource(NotificationSource):
    """身份有效期提醒（降权预警）：到期前两个月 / 一个月各一次。

    事件名与 ``accounts.validity_notices.LEVELS`` 对齐；幂等靠那边的 ``ValidityNotice``
    台账（同一到期时间只发一次），故本源不声明 ``dedup_identity``。
    """

    key = "validity"
    name = "身份有效期"
    description = "认证 / 管理员身份到期前的提醒（到期会降权）"
    color = "#a8551b"
    emoji = "⏳"
    events = (
        Event("expiring_2m", "身份有效期还剩两个月"),
        Event("expiring_1m", "身份有效期还剩一个月"),
    )
    default_channels = ("site",)
