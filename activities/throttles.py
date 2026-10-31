"""活动端点限流。

目前只有一处：公开受众的游客投票。游客按客户端 ``X-Device-Id`` 判重
（ADR-0019），而设备号由客户端生成、可无限轮换——判重挡不住脚本刷票，
所以在服务端再按（IP + 活动）加一道时间窗限流兜底。

登录用户的票按账号判重，不计入本限流（``AnonRateThrottle`` 对已登录请求
返回空缓存键）。额度住在 ``SiteSettings``（``get_policy()``），不读
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``。
"""
import math

from rest_framework.exceptions import Throttled
from rest_framework.throttling import AnonRateThrottle

from common.policy import get_policy


class PublicVoteThrottle(AnonRateThrottle):
    """公开投票：每 IP 每活动每小时 N 票（只计未登录请求）。

    缓存键带上活动 id：一场正在进行的评选不应把同一出口 IP 在另一场
    活动上的投票额度也耗尽（学校 NAT 场景尤其明显）。
    """

    scope = "public_vote"

    def get_rate(self):
        return f"{get_policy().public_vote_per_ip_per_hour}/hour"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return None
        ident = self.get_ident(request)
        activity = (getattr(view, "kwargs", None) or {}).get("pk") or "unknown"
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{ident}:{activity}",
        }

    def throttle_failure(self):
        wait = self.wait()
        minutes = max(1, math.ceil(wait / 60))
        raise Throttled(
            wait=wait,
            detail=f"该网络的投票请求过于频繁，请约 {minutes} 分钟后再试。",
        )
