from django.http import HttpResponse, JsonResponse
from rest_framework.throttling import SimpleRateThrottle

from common.policy import get_policy


class _IPLimitThrottle(SimpleRateThrottle):
    """按 IP 计数的限流基类（用于函数式视图：手动实例化 + allow_request）。

    SimpleRateThrottle 的 get_cache_key 是抽象的，须覆写；这里固定用 self.scope +
    请求方 IP 作缓存键（与 DRF 内置 AnonRateThrottle 同形），不依赖 view 实例。
    """

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def is_blocked(self, request, view=None):
        """Peek: True if the next allow_request would deny. Does not increment."""
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return False
        self.history = list(self.cache.get(self.key, []))
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        return len(self.history) >= self.num_requests

    def retry_after(self, request, view=None):
        if not self.is_blocked(request, view):
            return 0
        wait = self.wait()
        return max(0, int(wait or 0))


class RegisterThrottle(_IPLimitThrottle):
    """自助注册节流：每个 IP 每天 N 次（N 来自 get_policy()）。"""

    scope = "register"

    def get_rate(self):
        return f"{get_policy().register_per_ip_per_day}/day"


class ResendVerificationThrottle(_IPLimitThrottle):
    """重发邮箱验证邮件节流：每个 IP 每小时 N 次（N 来自 get_policy()）。"""

    scope = "resend_verification"

    def get_rate(self):
        return f"{get_policy().resend_verification_per_ip_per_hour}/hour"


class AuthCodeRedeemThrottle(_IPLimitThrottle):
    """认证码兑换节流：每个账号每小时 N 次失败（N 来自 get_policy()）。

    按账号（user.pk）计数、**只计失败**——成功兑换不占额度；调用方在兑换失败时
    显式调用 allow_request 记账（与登录节流同口径）。
    """

    scope = "authcode_redeem"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False) or not user.pk:
            return None
        return self.cache_format % {"scope": self.scope, "ident": f"u{user.pk}"}

    def get_rate(self):
        return f"{get_policy().authcode_redeem_per_user_per_hour}/hour"


class MemberClaimThrottle(_IPLimitThrottle):
    """自助认领节流：每账号每小时 N 次失败（N 来自 get_policy()）。

    按账号（user.pk）计数、**只计失败**——成功认领不占额度；调用方在失败时
    显式调用 allow_request 记账（与认证码兑换同口径）。
    """

    scope = "member_claim"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False) or not user.pk:
            return None
        return self.cache_format % {"scope": self.scope, "ident": f"u{user.pk}"}

    def get_rate(self):
        return f"{get_policy().member_claim_per_user_per_hour}/hour"


class MemberClaimIpThrottle(_IPLimitThrottle):
    """自助认领节流：每 IP 每天 N 次失败（N 来自 get_policy()）。"""

    scope = "member_claim_ip"

    def get_rate(self):
        return f"{get_policy().member_claim_per_ip_per_day}/day"


class MemberCheckThrottle(_IPLimitThrottle):
    """扫码校验公开端点频控：每 IP 每小时 N 次（计全部请求）。"""

    scope = "member_check"

    def get_rate(self):
        return f"{get_policy().member_check_per_ip_per_hour}/hour"


class LoginIpThrottle(_IPLimitThrottle):
    """登录失败节流：每个 IP 每小时 N 次（N 来自 get_policy()）。"""

    scope = "login"

    def get_rate(self):
        return f"{get_policy().login_per_ip_per_hour}/hour"


class LoginUsernameThrottle(_IPLimitThrottle):
    """登录失败节流：每个用户名（或邮箱）每小时 N 次。

    ident 来自 request._login_throttle_ident（由调用方写入），不是 IP。
    """

    scope = "login_username"

    def get_cache_key(self, request, view):
        ident = (getattr(request, "_login_throttle_ident", None) or "").strip().lower()
        if not ident:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def get_rate(self):
        return f"{get_policy().login_per_username_per_hour}/hour"


def _attach_ident(request, username):
    request._login_throttle_ident = (username or "").strip().lower()


def is_login_blocked(request, username=""):
    _attach_ident(request, username)
    return LoginIpThrottle().is_blocked(request) or LoginUsernameThrottle().is_blocked(request)


def record_login_failure(request, username=""):
    """Count a failed password check. Successful logins do not call this."""
    _attach_ident(request, username)
    LoginIpThrottle().allow_request(request, None)
    LoginUsernameThrottle().allow_request(request, None)


def login_retry_after(request, username=""):
    _attach_ident(request, username)
    return max(
        LoginIpThrottle().retry_after(request),
        LoginUsernameThrottle().retry_after(request),
    )


def login_blocked_response(request, username="", *, as_html=False):
    """429 if this login is blocked, else None."""
    if not is_login_blocked(request, username):
        return None
    retry = login_retry_after(request, username)
    if as_html:
        resp = HttpResponse(
            "登录尝试过于频繁，请稍后再试。",
            status=429,
            content_type="text/html; charset=utf-8",
        )
        if retry:
            resp["Retry-After"] = str(retry)
        return resp
    body = {
        "error": "登录尝试过于频繁，请稍后再试。",
        "reason": "login_throttled",
        "retry_after": retry,
    }
    resp = JsonResponse(body, status=429)
    if retry:
        resp["Retry-After"] = str(retry)
    return resp
