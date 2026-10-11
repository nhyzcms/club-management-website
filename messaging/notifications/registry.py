"""源与通道的注册表（进程内单例）。

源与通道都是代码级注册：新增一种 = 写一个类 + ``@register_*``。
数据库只存「用户订阅」（NotificationSubscription）与「投递记录」（NotificationDelivery）。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    """源内的事件类型（Phase 1 用于展示与校验；订阅粒度为源级）。"""

    key: str
    name: str


class NotificationSource:
    """通知源基类。子类声明 key / name / description / events / default_channels / 视觉标识。"""

    key: str = ""
    name: str = ""
    description: str = ""
    events: tuple = ()
    default_channels: tuple = ("site",)
    color: str = "#0756a2"  # 源主色（邮件头部/标签、界面标识）
    emoji: str = "🔔"       # 源图标（邮件与界面）

    def dedup_identity(self, event: str, payload: Mapping) -> str | None:
        """同一「未读事项」的身份串；``None`` = 不聚合（每条都单独通知）。

        返回非空串的源：收件人已有同键**未读**通知时不再新建，只把最新载荷并进
        既有那条（见 ``messaging.notifications.dispatch``）；该通知被读掉之后，
        下一条同事项才重新通知。
        """
        return None

    def dedup_key(self, event: str, payload: Mapping) -> str:
        """未读聚合键 ``源:事件:事项``；不聚合时返回空串。

        同一 (源, 事件, 事项) 在**未读**期间只保留一条通知；事件进键，故同一对象上
        的不同事件（如活动「发布」与「开始」）各算各的事项。
        """
        identity = self.dedup_identity(event, payload)
        if not identity:
            return ""
        return f"{self.key}:{event}:{identity}"[:200]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Source {self.key}>"


class BaseChannel:
    """投递通道基类。"""

    key: str = ""
    name: str = ""
    description: str = ""
    uses_shared_connection: bool = False  # 是否复用投递队列的共享外发连接（如 email 的 SMTP）

    def is_available(self, user) -> bool:
        """该用户当前是否可用此通道（如邮箱已验证）。"""
        return True

    def deliver(self, delivery, *, connection=None) -> None:
        """投递一条 NotificationDelivery；失败请抛异常（队列按退避重试）。

        ``connection``：可选共享外发连接（如复用的 SMTP 会话），由投递队列传入；
        为 ``None`` 时自行处理（与历史行为一致）。
        """
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Channel {self.key}>"


_SOURCES: dict[str, NotificationSource] = {}
_CHANNELS: dict[str, BaseChannel] = {}


def register_source(cls):
    """类装饰器：注册通知源（类或实例均可）。"""
    inst = cls() if isinstance(cls, type) else cls
    if not inst.key:
        raise ValueError("NotificationSource 必须有非空 key")
    _SOURCES[inst.key] = inst
    return cls


def register_channel(cls):
    """类装饰器：注册投递通道（类或实例均可）。"""
    inst = cls() if isinstance(cls, type) else cls
    if not inst.key:
        raise ValueError("BaseChannel 必须有非空 key")
    _CHANNELS[inst.key] = inst
    return cls


def get_source(key: str):
    return _SOURCES.get(key)


def get_channel(key: str):
    return _CHANNELS.get(key)


def all_sources() -> list:
    return sorted(_SOURCES.values(), key=lambda s: s.key)


def all_channels() -> list:
    return sorted(_CHANNELS.values(), key=lambda c: c.key)
