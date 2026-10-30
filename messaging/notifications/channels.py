"""内置投递通道：站内 / 邮件 / Webhook（预留）/ 短信（预留）。

``deliver(delivery, *, connection=None)``：投递一条投递行；失败请抛异常
（异步模式由投递队列按退避重试；同步模式仅留痕）。``connection`` 为投递队列
传入的共享外发连接（见 ``BaseChannel.uses_shared_connection``），``None`` 时自建。
"""
from __future__ import annotations

import logging
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .registry import BaseChannel, get_source, register_channel

logger = logging.getLogger(__name__)


def _event_name(source, event_key: str) -> str:
    """事件展示名（回退到原始 key）。"""
    if source:
        for ev in getattr(source, "events", ()) or ():
            if ev.key == event_key:
                return ev.name
    return event_key


def _absolute_url(path: str) -> str:
    """相对路径 → 绝对 URL（邮件客户端无站点上下文）。

    前端是 **HashRouter**（``/#/news/42``），payload 里的 url 一律是路由路径（``/news/42``）。
    所以这里必须补上 ``/#`` 前缀——否则邮件里的链接打开的是 ``https://站点/news/42``：
    服务端返回入口 HTML，HashRouter 看到空 hash 就落到首页，收件人永远到不了目标页。
    已经是绝对地址或已带 ``/#`` 的原样返回。
    """
    path = (path or "").strip()
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if not base:
        return path
    if base.endswith("#"):
        base = base[:-1]
    if path.startswith("/#"):
        return f"{base}{path}"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}/#{path}"


def _tint(hex_color: str, ratio: float = 0.88) -> str:
    """主色的浅色底（源标签 pill 背景用）。"""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:  # pragma: no cover - 防御性
        return "#eef4fa"

    def mix(c: int) -> int:
        return int(c + (255 - c) * ratio)

    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


def _copy_for(category: str, event: str, payload: dict) -> str:
    """通知正文文案（按源与事件个性化；对象类附名称）。"""
    obj_title = (payload.get("title") or "").strip()
    quoted = f"「{obj_title}」" if obj_title else ""
    if category == "review":
        if event == "feedback_submitted":
            return f"{quoted or '有用户'}提交了新的意见反馈，请前往查看并处理。"
        if event == "content_submitted":
            return f"{quoted or '有新内容'}等待审核，请前往审核工作台处理。"
        if event == "report_submitted":
            return "有新的举报提交，请前往审核工作台查看处理。"
        if event == "identity_submitted":
            return "有新的身份认证申请提交，请前往审核工作台处理。"
        if event == "identity_resolved":
            if payload.get("result") == "approved":
                return "你的身份认证已通过审核，现在可以使用全部功能了。"
            return "你的身份证明材料未通过审核，可在「账号认证」面板重新提交更清晰的材料。"
        if event == "report_resolved":
            if payload.get("result") == "upheld":
                return "你提交的举报已成立并完成处置，感谢你的反馈。"
            return "你提交的举报经核实后未予处理，感谢你的反馈。"
        if event == "closed":
            return "你提交的意见反馈已被处理了结。"
    if category == "activity":
        if event == "published":
            return f"{quoted or '新互动'}已发布上线，快来看看吧！"
        if event == "opened":
            return f"{quoted or '互动'}已开始，现在可以参与了。"
    if category == "comment":
        if event == "comment_replied":
            return "有人回复了你的评论，点击查看详情。"
        if event == "comment_mentioned":
            return "有人在评论中提到了你，点击查看详情。"
    if category == "dm":
        return "你收到了一条新私信，登录后即可查看。"
    if category == "announcement":
        lead = f"全站公告{quoted}。" if quoted else "全站发布了新的公告。"
        summary = (payload.get("summary") or "").strip()
        return f"{lead}{summary}" if summary else f"{lead}点击查看全文。"
    if category == "discipline":
        if event == "muted":
            return "你的账号已被禁言，期间暂时无法发言。"
        if event in ("mute_lifted", "mute_expired"):
            return "你的禁言已解除，现在可以正常发言了。"
    if category == "validity":
        label = (payload.get("channel_label") or "身份").strip()
        expires_on = (payload.get("expires_on") or "").strip()
        when = f"（{expires_on} 到期）" if expires_on else ""
        return (
            f"你的{label}即将到期{when}。到期后相关权限会被收回（管理员身份被撤销、"
            "成员认证状态回落为访客）；如仍需保留，请尽快联系社长或服务器管理员续期。"
        )
    return "你有一条新通知，登录站点即可查看完整内容。"


@register_channel
class SiteChannel(BaseChannel):
    """站内：通知在 dispatch 时已落库并 push；本通道不做额外投递。"""

    key = "site"
    name = "站内"
    description = "站内通知列表与未读提醒"

    def deliver(self, delivery, *, connection=None) -> None:
        return None


@register_channel
class EmailChannel(BaseChannel):
    """邮件：发送带社团徽标的 HTML 通知到用户已认证邮箱（每源独立配色）。

    ``connection``：由投递队列传入的复用 SMTP 连接（批量发送共享一个会话）；
    ``None`` 时自建连接（与历史行为一致）。
    """

    key = "email"
    name = "邮件"
    description = "将通知摘要发送到邮箱（需已完成认证）"
    uses_shared_connection = True  # 复用投递队列的 SMTP 连接

    def is_available(self, user) -> bool:
        from accounts.models import is_verified

        email = (getattr(user, "email", None) or "").strip()
        if not email:
            return False
        try:
            return bool(is_verified(user))
        except Exception:  # pragma: no cover - 防御性
            return False

    def deliver(self, delivery, *, connection=None) -> None:
        notification = delivery.notification
        user = notification.recipient
        email = (getattr(user, "email", None) or "").strip()
        if not email:
            raise ValueError("用户没有可用邮箱")

        source = get_source(notification.category)
        source_name = source.name if source else "站内"
        color = (getattr(source, "color", "") or "#0756a2") if source else "#0756a2"
        emoji = (getattr(source, "emoji", "") or "🔔") if source else "🔔"
        event_name = _event_name(source, notification.event)

        payload = notification.payload or {}
        url = _absolute_url(payload.get("url"))
        message = _copy_for(notification.category, notification.event, payload)

        # 公告以标题作邮件主题（比「公告发布」有用得多）；其余源保持「源·事件」。
        obj_title = str(payload.get("title") or "").strip()
        if notification.category == "announcement" and obj_title:
            subject = f"【南汇一中传媒社】{obj_title}"
        else:
            subject = f"【南汇一中传媒社·{source_name}】{event_name}"
        html = render_to_string(
            "messaging/notifications/email.html",
            {
                "color": color,
                "tint": _tint(color),
                "emoji": emoji,
                "source_name": source_name,
                "title": event_name,
                "message": message,
                "url": url,
            },
        )
        text_lines = [event_name, "", message]
        if url:
            text_lines += ["", f"详情：{url}"]
        text_lines += ["", "（可在「个人中心 → 通知设置」中调整通知方式）"]

        msg = EmailMultiAlternatives(
            subject=subject,
            body="\n".join(text_lines),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[email],
            connection=connection,
        )
        msg.attach_alternative(html, "text/html")

        logo_path = Path(__file__).resolve().parent.parent / "assets" / "club_logo.png"
        if logo_path.exists():
            image = MIMEImage(logo_path.read_bytes(), _subtype="png")
            image.add_header("Content-ID", "<club-logo>")
            image.add_header("Content-Disposition", "inline", filename="club-logo.png")
            msg.attach(image)

        msg.send(fail_silently=False)


@register_channel
class WebhookChannel(BaseChannel):
    """Webhook：向用户配置的 URL POST 通知载荷（P2 实现投递）。"""

    key = "webhook"
    name = "Webhook"
    description = "将通知 JSON POST 到自定义 URL（即将支持）"

    def is_available(self, user) -> bool:
        return False

    def deliver(self, delivery, *, connection=None) -> None:
        raise NotImplementedError("Webhook 通道尚未开放")


@register_channel
class SmsChannel(BaseChannel):
    """短信：留接口，待服务商选型。"""

    key = "sms"
    name = "短信"
    description = "短信通知（即将支持）"

    def is_available(self, user) -> bool:
        return False

    def deliver(self, delivery, *, connection=None) -> None:
        raise NotImplementedError("短信通道尚未接入服务商")
