from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from common.policy import get_policy


class FeedbackAnonThrottle(AnonRateThrottle):
    """匿名意见反馈节流：每个 IP 每天 N 条（N 来自 get_policy()）。

    继承 AnonRateThrottle —— 仅对未登录请求按 IP 计数；已登录用户不计入。
    """

    scope = "feedback_anon"

    def get_rate(self):
        return f"{get_policy().feedback_anon_per_ip_per_day}/day"


class ReportDailyThrottle(UserRateThrottle):
    """已认证成员举报节流：每用户每天 N 条（N 来自 get_policy()）。"""

    scope = "reports_user"

    def get_rate(self):
        return f"{get_policy().reports_per_user_per_day}/day"
