"""访客标识：设备标识（ADR 0014）与客户端 IP。

浏览器没有稳定硬件 ID；门户生成 UUID 写入 localStorage，请求带 ``X-Device-Id``。
未登录作答/投票按 (对象, 设备标识) 一人一份，防刷单/刷票；游客投票另记录 IP 备查。
"""
import re

from rest_framework.request import Request

DEVICE_ID_HEADER = "HTTP_X_DEVICE_ID"
DEVICE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def device_id_from_request(request: Request) -> str:
    """读 ``X-Device-Id``；缺或非法返回空串。"""
    raw = (request.META.get(DEVICE_ID_HEADER) or "").strip()
    if not raw or not DEVICE_ID_RE.fullmatch(raw):
        return ""
    return raw.lower()


def client_ip_from_request(request: Request) -> str:
    """客户端 IP：生产为 Nginx（``$proxy_add_x_forwarded_for``）反代，真实 IP 由
    Nginx 追加在 ``X-Forwarded-For`` **末段**（最左可被客户端伪造，不可信）；
    无该头时回退 ``REMOTE_ADDR``（开发直连 / 无代理部署）。
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return (request.META.get("REMOTE_ADDR") or "").strip()
