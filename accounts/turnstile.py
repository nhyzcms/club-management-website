"""Cloudflare Turnstile 服务端校验。

开关：``TURNSTILE_SITE_KEY`` 与 ``TURNSTILE_SECRET_KEY`` **都非空**才启用。
任一为空 → 关闭：校验直接通过、公开快照不下发 sitekey。
用于自助注册、找回密码、重发认证信、匿名意见反馈。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.http import JsonResponse

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
FAIL_MESSAGE = "人机校验失败，请刷新后重试。"


def _site_key():
    return (getattr(settings, "TURNSTILE_SITE_KEY", None) or "").strip()


def _secret_key():
    return (getattr(settings, "TURNSTILE_SECRET_KEY", None) or "").strip()


def is_turnstile_enabled():
    """两项都配了才开；只配一半视为关闭，避免前端无挂件而后端拒注册。"""
    return bool(_site_key() and _secret_key())


def public_turnstile_fields():
    """给 SPA 的公开字段。secret 永不下发；未启用时 sitekey 也留空。"""
    enabled = is_turnstile_enabled()
    return {
        "turnstile_enabled": enabled,
        "turnstile_site_key": _site_key() if enabled else "",
    }


def verify_turnstile(token, remote_ip=""):
    """校验 Turnstile token。返回 True 表示通过（或功能已关闭）。"""
    if not is_turnstile_enabled():
        return True
    if not token:
        return False
    data = urllib.parse.urlencode(
        {
            "secret": _secret_key(),
            "response": token,
            "remoteip": remote_ip or "",
        }
    ).encode()
    req = urllib.request.Request(SITEVERIFY_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 — 受信 URL
            result = json.loads(resp.read().decode())
            return bool(result.get("success"))
    except (urllib.error.URLError, OSError, ValueError):
        # 网络故障 / 解析失败 → 视为未通过（不因网络抖动放行机器人）。
        return False


def passes_turnstile(request, token=""):
    """结合请求 IP 做校验。功能关闭时恒为 True。"""
    from .utils import get_client_ip

    return verify_turnstile(token or "", get_client_ip(request))


def turnstile_error_response(*, drf=False):
    """启用且校验未通过时的 400。``drf=True`` 用 ``detail``（REST 视图）。"""
    if drf:
        from rest_framework.response import Response

        return Response({"detail": FAIL_MESSAGE}, status=400)
    return JsonResponse({"error": FAIL_MESSAGE}, status=400)
