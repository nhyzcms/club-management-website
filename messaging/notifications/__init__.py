"""通知框架：源（Source）× 通道（Channel）× 订阅（Subscription）。

对外暴露注册表与 dispatch；业务代码继续经 ``messaging.services.notify()`` 调用。
"""
from .registry import (  # noqa: F401
    BaseChannel,
    Event,
    NotificationSource,
    all_channels,
    all_sources,
    get_channel,
    get_source,
    register_channel,
    register_source,
)
from .dispatch import dispatch, subscribed_channels  # noqa: F401
