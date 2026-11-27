"""File-flag maintenance page: 503 HTML without touching the database."""
import base64
import binascii
import hmac
import os
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string

from common.maintenance import REASON_UPDATE, read_status

#: 探测端点不参与 Basic 闸门：容器 healthcheck / 反代探活拿不到用户密码。
BASIC_AUTH_EXEMPT_PATHS = frozenset({"/healthz", "/healthz/"})

# Cheap exists() check each request so an updater / ops can flip the flag
# without restarting Gunicorn. Path is relative to BASE_DIR, not cwd.
MAINTENANCE_FLAG_PATH = Path(settings.BASE_DIR) / "run" / "MAINTENANCE"


class MaintenanceModeMiddleware:
    """If ``run/MAINTENANCE`` exists, return a 503 page and skip the rest of the stack.

    ``render_to_string`` with no request — no context processors, sessions, CSRF,
    or database. Inline CSS only; does not depend on ``frontend/dist``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not MAINTENANCE_FLAG_PATH.exists():
            return self.get_response(request)
        status = read_status(MAINTENANCE_FLAG_PATH)
        html = render_to_string("maintenance.html", {"status": status})
        response = HttpResponse(html, status=503)
        response["Cache-Control"] = "no-store"
        response["Retry-After"] = "5" if status and status.reason == REASON_UPDATE else "120"
        return response


class BasicAuthGateMiddleware:
    """HTTP Basic 闸门：只由环境变量显式启用，专供 test 环境。

    动机：test 环境带 ``DJANGO_DEBUG=1`` 且直接挂公网（不经 nginx），
    错误页会给出 traceback / 局部变量 / settings 片段。用一层 Basic 认证
    把「谁能看这些」限定在拿到测试账号的人。

    生产是 **no-op**：两个变量都没配时直接放行——默认有关卡会让一次
    部署漏配变量变成「线上全站 401」。反过来，只配了一半也按未启用处理，
    避免半吊子配置把站点锁死在一个没人知道的密码后面。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        expected_user = os.environ.get("TEST_BASIC_AUTH_USER", "")
        expected_password = os.environ.get("TEST_BASIC_AUTH_PASSWORD", "")
        if not expected_user or not expected_password:
            return self.get_response(request)
        if request.path in BASIC_AUTH_EXEMPT_PATHS:
            return self.get_response(request)
        if self._authorized(request, expected_user, expected_password):
            return self.get_response(request)

        response = HttpResponse(
            "Authentication required.",
            status=401,
            content_type="text/plain; charset=utf-8",
        )
        response["WWW-Authenticate"] = 'Basic realm="club-test", charset="UTF-8"'
        response["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def _authorized(request, expected_user, expected_password):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "basic" or not token:
            return False
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        user, sep, password = decoded.partition(":")
        if not sep:
            return False
        try:
            # compare_digest 只接受 ASCII str / bytes：非 ASCII 输入若直接比较
            # 会抛 TypeError（500），这里统一编码后比较并吞掉编码失败。
            return hmac.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8")) and hmac.compare_digest(
                password.encode("utf-8"), expected_password.encode("utf-8")
            )
        except UnicodeEncodeError:
            return False
