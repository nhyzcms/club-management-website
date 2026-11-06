"""活动端点限流。

两处消费端：

1. 公开受众的游客投票。游客按客户端 ``X-Device-Id`` 判重（ADR-0019），而设备号
   由客户端生成、可无限轮换——判重挡不住脚本刷票，所以在服务端再按（IP + 活动）
   加一道时间窗限流兜底。登录用户的票按账号判重，不计入本限流
   （``AnonRateThrottle`` 对已登录请求返回空缓存键）。
2. 问卷文件题上传（``survey_upload``）。这是全站唯一匿名可写的上传端点，原先
   没有任何节流（审计 #271）。按 IP 与设备号各计一道，两者都**计全部请求**
   （登录用户也计）——注册一个账号就能绕过 ``AnonRateThrottle``，而滥用者
   最不缺的就是账号。

额度全部住在站点策略（``get_policy()``），不读
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``。
"""
import math

from rest_framework.exceptions import Throttled
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle

from common.policy import get_policy

from .device import client_ip_from_request, device_id_from_request


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


class _SurveyUploadThrottle(SimpleRateThrottle):
    """问卷上传限流基类：对**所有**请求计数（含登录用户），子类只换 cache 键。"""

    scope = "survey_upload"

    def get_cache_key(self, request, view):  # pragma: no cover - 子类实现
        raise NotImplementedError

    def throttle_failure(self):
        wait = self.wait()
        minutes = max(1, math.ceil(wait / 60))
        raise Throttled(
            wait=wait,
            detail=f"上传过于频繁，请约 {minutes} 分钟后再试。",
        )


class SurveyUploadIPThrottle(_SurveyUploadThrottle):
    """问卷上传：每 IP 每小时 N 次。

    用 ``client_ip_from_request`` 而不是 DRF 的 ``get_ident``：前者与本项目
    其余 IP 判定（XFF 末段；生产 unix socket 下无 ``REMOTE_ADDR``）同源，
    避免「这里按一个值计数、审计里按另一个值记录」。
    """

    scope = "survey_upload_ip"

    def get_rate(self):
        return f"{get_policy().survey_upload_per_ip_per_hour}/hour"

    def get_cache_key(self, request, view):
        ip = client_ip_from_request(request)
        if not ip:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ip}


class SurveyUploadDeviceThrottle(_SurveyUploadThrottle):
    """问卷上传：每设备每小时 N 次。

    没带 ``X-Device-Id``（或格式非法）时返回 ``None`` = 不计数，此时只有 IP
    维度生效。不能把一个空标识当成所有匿名用户共用的一格——那样第一个人
    就能耗光全站额度。
    """

    scope = "survey_upload_device"

    def get_rate(self):
        return f"{get_policy().survey_upload_per_device_per_hour}/hour"

    def get_cache_key(self, request, view):
        device_id = device_id_from_request(request)
        if not device_id:
            return None
        return self.cache_format % {"scope": self.scope, "ident": device_id}
