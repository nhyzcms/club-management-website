"""明信片互寄限流（复用 ``common.throttles.IPLimitThrottle`` 基座）。

公开写端点（登记 / 建议）是全站暴露面最大的入口——活动期间任何访客可写，
双轨限流：**IP 轨**（学校 NAT 出口整层楼共用，阈值放宽）+ **设备轨**
（``ncdid`` Cookie，同一设备刷量绕不过 NAT 轨）。两轨任一触发即 429。

速率取值偏保守：登记是低频动作（一人一天最多几张），10/h 足够真人、
足够卡脚本；建议箱 5/h。管理端不限流（低频 + 已鉴权）。
"""
from common.throttles import IPLimitThrottle

from accounts.utils import device_id_from_request


class _DeviceOrIPThrottle(IPLimitThrottle):
    """设备优先、IP 兜底的限流键：有 ncdid 按设备计，没有按 IP 计。"""

    def get_cache_key(self, request, view):
        device = device_id_from_request(request)
        ident = f"d:{device}" if device else None
        if ident is None:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class RegisterIPThrottle(IPLimitThrottle):
    scope = "postcard_register_ip"
    RATE = "10/hour"

    def get_rate(self):
        return self.RATE


class RegisterDeviceThrottle(_DeviceOrIPThrottle):
    scope = "postcard_register_dev"
    RATE = "10/hour"

    def get_rate(self):
        return self.RATE


class SuggestionIPThrottle(IPLimitThrottle):
    scope = "postcard_suggest_ip"
    RATE = "5/hour"

    def get_rate(self):
        return self.RATE


class SuggestionDeviceThrottle(_DeviceOrIPThrottle):
    scope = "postcard_suggest_dev"
    RATE = "5/hour"

    def get_rate(self):
        return self.RATE
