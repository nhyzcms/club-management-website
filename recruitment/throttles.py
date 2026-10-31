"""招募「加入问卷」限流（审计 M-3）。

该端点匿名可提交、只按客户端 ``X-Device-Id`` 计 5 次上限——轮换设备号即可无限灌
报名（含大 JSON）。这里先加按 IP 的小时配额；Turnstile 由站点策略单独控制。
"""
from rest_framework.throttling import SimpleRateThrottle


class JoinAnswerThrottle(SimpleRateThrottle):
    scope = "join_answer"
    rate = "10/hour"

    def get_cache_key(self, request, view=None):
        ident = self.get_ident(request)
        if not ident:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}
