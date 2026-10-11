from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.utils import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.utils.html import escape

from .models import UserSession
from .throttles import login_blocked_response
from .utils import record_user_session
from .validity import enforce_account_validity


def _is_admin_login_post(request):
    return request.method == "POST" and request.path.rstrip("/") == "/admin/login"


def _prefers_html(request):
    """浏览器导航（Accept 含 text/html）→ 渲染 HTML 下线页；SPA / API 保持 JSON 契约。"""
    return "text/html" in (request.headers.get("Accept") or "")


# 被挤下线的浏览器导航页：卡片式提示 + 接管设备信息 + 重新登录入口。
# 注意：模板经 str.format 填充，CSS 花括号须写成 {{ }}。
_SUPERSEDED_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>您已被迫下线</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #f5f6f8; color: #1f2329; padding: 24px;
    font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  }}
  .card {{
    width: 100%; max-width: 430px; background: #fff; border-radius: 16px;
    box-shadow: 0 8px 30px rgba(15, 23, 42, .08); padding: 36px 30px 28px; text-align: center;
  }}
  .badge {{
    width: 56px; height: 56px; margin: 0 auto 18px; border-radius: 50%;
    background: #fff4e5; display: flex; align-items: center; justify-content: center; font-size: 26px;
  }}
  h1 {{ font-size: 19px; margin: 0 0 10px; }}
  p {{ margin: 0 0 10px; color: #4b5563; font-size: 14px; }}
  .device {{
    margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: #f8fafc;
    border: 1px solid #eef2f7; color: #334155; font-size: 13px; text-align: left;
  }}
  .device div {{ margin: 3px 0; }}
  .device b {{ color: #0f172a; font-weight: 600; }}
  .btn {{
    display: inline-block; margin-top: 18px; padding: 11px 26px; border-radius: 10px;
    background: #2563eb; color: #fff; text-decoration: none; font-size: 14px; font-weight: 500;
  }}
  .btn:hover {{ background: #1d4ed8; }}
  .foot {{ margin-top: 16px; font-size: 12px; color: #9ca3af; }}
</style>
</head>
<body>
  <main class="card">
    <div class="badge">🔒</div>
    <h1>您已被迫下线</h1>
    <p>您的账号已在另一台设备登录，当前设备已退出登录。</p>
    <div class="device">
      <div>接管设备：<b>{device_name}</b>（{device_type}）</div>
      <div>登录时间：<b>{time}</b></div>
    </div>
    <p>如非本人操作，请尽快重新登录并修改密码。</p>
    <a class="btn" href="{login_url}">重新登录</a>
    <div class="foot">南汇一中传媒社</div>
  </main>
</body>
</html>"""


def _superseded_page(current):
    """渲染下线页：登录时间转北京时间展示；所有插值先转义（device_name 来自 UA）。"""
    local = current.created_at.astimezone(ZoneInfo("Asia/Shanghai"))
    return _SUPERSEDED_HTML.format(
        device_name=escape(current.device_name or "未知设备"),
        device_type=escape(current.device_type or "未知"),
        time=escape(local.strftime("%Y-%m-%d %H:%M") + "（北京时间）"),
        login_url=escape(getattr(settings, "FRONTEND_URL", "") or "/"),
    )


class LoginThrottleMiddleware:
    """Block /admin/login/ POSTs that already exceeded the failure budget.

    The portal login view checks the same helpers itself. Recording still
    happens on user_login_failed (admin authenticate + portal send).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_admin_login_post(request):
            username = request.POST.get("username", "")
            blocked = login_blocked_response(request, username, as_html=True)
            if blocked is not None:
                return blocked
        return self.get_response(request)


class SingleSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            session_key = request.session.session_key
            current = (
                UserSession.objects
                .filter(user=user, is_current=True)
                .order_by("-created_at")
                .first()
            )
            if current is None:
                # Session that predates this feature: adopt it as the current one
                if session_key:
                    record_user_session(request, user, session_key)
            elif current.session_key != session_key:
                # Another device logged in → this session is superseded
                request.session.flush()
                takeover = {
                    "device_name": current.device_name,
                    "device_type": current.device_type,
                    "ip": current.ip_address,
                    "time": current.created_at.isoformat(),
                }
                if _prefers_html(request):
                    # 浏览器直接访问（如手机打开站点）→ 友好 HTML 页；
                    # SPA / API 请求（Accept 不含 text/html）保持 JSON 契约（#10）。
                    return HttpResponse(
                        _superseded_page(current),
                        status=401,
                        content_type="text/html; charset=utf-8",
                    )
                return JsonResponse(
                    {
                        "detail": "您的账号在其他设备登录，您已被迫下线。",
                        "reason": "session_superseded",
                        "takeover": takeover,
                    },
                    status=401,
                )
        return self.get_response(request)


class ValidityEnforcementMiddleware:
    """惰性执行身份有效期（ADR-0041，请求时兜底）。

    在响应后执行：撤销过期管理员 / 停用超期未认证账号。放在 AuthenticationMiddleware 之后，
    用已加载的 ``request.user`` 判定，只对「可能受影响」的用户做一次廉价检查（超管 /
    近期注册用户直接跳过）。变更在下一次请求生效，不干扰当前响应与会话。

    对 ``DatabaseError`` 静默跳过：迁移测试会把 schema 迁到旧状态（表缺列），此时惰性执行
    不可用；生产 schema 恒最新不会走到这里，定时命令兜底。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            try:
                enforce_account_validity(user)
            except DatabaseError:
                pass
        return response
