import time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.utils import DatabaseError
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils.html import escape

from .models import Profile, UserSession
from .throttles import login_blocked_response
from .utils import (
    DEVICE_COOKIE_MAX_AGE,
    DEVICE_COOKIE_NAME,
    device_id_from_request,
    new_device_id,
    record_user_session,
    touch_user_session,
)
from .validity import enforce_account_validity

# 惰性有效期检查的会话级节流间隔（秒）：同一会话内至多隔这么久做一次检查。
#
# 为什么需要：本中间件原先**每个已登录请求**都跑一遍 enforce_account_validity，而这
# 对普通用户就是一次 EXISTS 查询（未认证者还要再读 Profile）—— 实测每个已登录请求固定
# 多 1~3 条 SQL，包括 /auth/csrf/ 这类空接口。但「管理员过期 / 注册超期」是慢变化事件，
# 不值得按请求去查。
# 语义代价：过期撤销最坏延迟一个间隔生效。可接受，因为
#   ① 登录路径仍即时检查（accounts 登录流程直接调 enforce_account_validity）；
#   ② 定时命令 manage.py enforce_validity 兜底；
#   ③ 变更本身是「降权 / 停用」，延迟几分钟不会造成越权（检查的是本会话的用户）。
VALIDITY_CHECK_INTERVAL_SECONDS = 300
_VALIDITY_CHECKED_AT_KEY = "validity_checked_at"


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
<title>{title}</title>
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
    <h1>{title}</h1>
    <p>{message}</p>
    <div class="device">{device_block}</div>
    <p>如非本人操作，请尽快重新登录并修改密码。</p>
    <a class="btn" href="{login_url}">重新登录</a>
    <div class="foot">南汇一中传媒社</div>
  </main>
</body>
</html>"""

# 下线原因 → （标题, 说明）。默认是「另一台设备登录顶替」。
_REVOKE_COPY = {
    UserSession.REVOKE_LIMIT: (
        "该设备已退出登录",
        "你的账号最多同时保持 3 台设备登录。有新设备登录时，最久未使用的那台会被替换下线——"
        "可在「个人中心 → 登录设备」里查看与管理。",
    ),
    UserSession.REVOKE_MANUAL: (
        "该设备已被下线",
        "这台设备已在「个人中心 → 登录设备」中被下线。",
    ),
    UserSession.REVOKE_REPLACED: (
        "该设备已重新登录",
        "这台设备上的旧会话已被同一设备的新登录替换。",
    ),
    UserSession.REVOKE_SECURITY: (
        "账号安全状态已变更",
        "账号安全状态发生变化（停用 / 重置密码 / 撤销认证等），请重新登录。",
    ),
}
_DEFAULT_REVOKE_COPY = ("您已被迫下线", "您的账号已在另一台设备登录，当前设备已退出登录。")


def revoke_copy(reason):
    return _REVOKE_COPY.get(reason, _DEFAULT_REVOKE_COPY)


def _superseded_page(takeover, revoked_reason=""):
    """渲染下线页：登录时间转北京时间展示；所有插值先转义（device_name 来自 UA）。"""
    title, message = revoke_copy(revoked_reason)
    device_block = ""
    if takeover is not None:
        local = takeover.created_at.astimezone(ZoneInfo("Asia/Shanghai"))
        device_block = (
            f"<div>接管设备：<b>{escape(takeover.device_name or '未知设备')}</b>"
            f"（{escape(takeover.device_type or '未知')}）</div>"
            f"<div>登录时间：<b>{escape(local.strftime('%Y-%m-%d %H:%M') + '（北京时间）')}</b></div>"
        )
    return _SUPERSEDED_HTML.format(
        title=escape(title),
        message=escape(message),
        device_block=device_block,
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


class MultiDeviceSessionMiddleware:
    """多端登录（ADR-0028）：同一账号最多 ``MAX_ACTIVE_SESSIONS``（3）台设备同时在线。

    判定唯一真源是 ``UserSession.revoked_at``：

    * 本会话没有记录（早于本功能的老会话）→ 补登记（占用一个名额）；
    * 本会话已下线 → ``flush()`` + 401（浏览器导航给 HTML 下线页，SPA / API 给
      JSON 契约 ``session_superseded`` + ``revoked_reason`` + 接管设备信息）；
    * 在线 → 补设备 Cookie、节流刷新 ``last_seen_at``。

    同时给每位访客下发 ``club_device`` Cookie（HttpOnly，2 年）：同一台设备重新登录时
    复用自己的名额，不会因为「重新登录」多占一个名额。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self._guard(request)
        if response is None:
            response = self.get_response(request)
        if not device_id_from_request(request):
            response.set_cookie(
                DEVICE_COOKIE_NAME,
                new_device_id(),
                max_age=DEVICE_COOKIE_MAX_AGE,
                httponly=True,
                samesite="Lax",
                secure=request.is_secure(),
            )
        return response

    def _guard(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        session_key = request.session.session_key
        if not session_key:
            return None
        row = UserSession.objects.filter(session_key=session_key).first()
        if row is None or row.user_id != user.id:
            # 老会话 / 会话与设备记录不一致 → 按未登记处理，补一条在线记录。
            record_user_session(request, user, session_key)
            return None
        if row.revoked_at is not None:
            return self._kick_out(request, user, row)
        if not row.device_id:
            cookie = device_id_from_request(request)
            if cookie:
                row.device_id = cookie
                row.save(update_fields=["device_id"])
        touch_user_session(request, row)
        return None

    def _kick_out(self, request, user, row):
        """已下线设备：清会话并返回 401（含下线原因与接管设备，供前端弹窗）。"""
        request.session.flush()
        takeover = None
        if row.replaced_by_session_key:
            takeover = (
                UserSession.objects
                .filter(session_key=row.replaced_by_session_key)
                .first()
            )
        if takeover is None:
            takeover = (
                UserSession.objects
                .filter(user=user, revoked_at__isnull=True)
                .order_by("-created_at")
                .first()
            )
        payload = {
            "detail": revoke_copy(row.revoked_reason)[1],
            "reason": "session_superseded",
            "revoked_reason": row.revoked_reason,
            "takeover": {
                "device_name": takeover.device_name,
                "device_type": takeover.device_type,
                "ip": takeover.ip_address,
                "time": takeover.created_at.isoformat(),
            } if takeover is not None else {},
        }
        if _prefers_html(request):
            # 浏览器直接访问（如手机打开站点）→ 友好 HTML 页；
            # SPA / API 请求（Accept 不含 text/html）保持 JSON 契约（#10）。
            return HttpResponse(
                _superseded_page(takeover, row.revoked_reason),
                status=401,
                content_type="text/html; charset=utf-8",
            )
        return JsonResponse(payload, status=401)


# 强制改密期间仍放行的路径：读取自身状态、改密、退出、开关后台改密页与静态资源。
# 其余请求一律 403（API）/ 重定向到后台改密页（/admin/）。
PASSWORD_CHANGE_EXEMPT_PREFIXES = (
    "/auth/me/",
    "/auth/password/force-change/",
    "/auth/logout/",
    "/auth/csrf/",
    "/auth/login/",
    "/admin/login/",
    "/admin/logout/",
    "/admin/password_change/",
    "/admin/jsi18n/",
    "/static/",
    "/media/",
    "/private-media/",
    "/favicon",
)


class PasswordChangeRequiredMiddleware:
    """管理员重置密码后的「首次登录必须改密」闸门。

    判定源是 ``Profile.must_change_password``；为省掉每个请求一次查询，结果缓存在
    session（登录视图会直接写入，改密成功后清零）。数据库异常（迁移测试把 schema
    迁到旧状态）时静默放行——与 ValidityEnforcementMiddleware 同口径。

    - SPA / API：403 JSON ``{"reason": "password_change_required"}``，前端拦截后跳改密页；
    - Django 后台：重定向到 ``/admin/password_change/``（否则管理员被自己的重置卡死）。
    """

    SESSION_KEY = "pwd_change_required"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and self._required(request)
            and not self._exempt(request.path)
        ):
            if request.path.startswith("/admin/"):
                return HttpResponseRedirect(reverse("admin:password_change"))
            return JsonResponse(
                {
                    "error": "管理员已重置你的密码，请先修改密码后再继续使用。",
                    "reason": "password_change_required",
                    "url": "/change-password-required",
                },
                status=403,
            )
        return self.get_response(request)

    def _required(self, request) -> bool:
        session = getattr(request, "session", None)
        if session is None:
            return False
        cached = session.get(self.SESSION_KEY)
        if isinstance(cached, bool):
            return cached
        try:
            required = Profile.objects.filter(
                user_id=request.user.pk, must_change_password=True,
            ).exists()
        except DatabaseError:
            return False
        session[self.SESSION_KEY] = required
        return required

    @staticmethod
    def _exempt(path: str) -> bool:
        normalized = path if path.endswith("/") else path + "/"
        return any(normalized.startswith(prefix) for prefix in PASSWORD_CHANGE_EXEMPT_PREFIXES)


class ValidityEnforcementMiddleware:
    """惰性执行身份有效期（ADR-0041，请求时兜底；带会话级节流）。

    在响应后执行：撤销过期管理员 / 停用超期未认证账号。放在 AuthenticationMiddleware 之后，
    用已加载的 ``request.user`` 判定，只对「可能受影响」的用户做一次廉价检查（超管 /
    近期注册用户直接跳过）。变更在下一次请求生效，不干扰当前响应与会话。

    节流（``VALIDITY_CHECK_INTERVAL_SECONDS``）：同一会话 N 秒内只检查一次，时间戳存
    session；只在真做了检查时才写 session，所以绝大多数请求既不查库也不写库。
    登录路径不受影响——登录流程自己会立即调一次 enforce_account_validity；定时命令
    （manage.py enforce_validity）继续兜底。

    对 ``DatabaseError`` 静默跳过：迁移测试会把 schema 迁到旧状态（表缺列），此时惰性执行
    不可用；生产 schema 恒最新不会走到这里，定时命令兜底。检查出错时不写时间戳，
    下一个请求会重试。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and self._due(request):
            try:
                enforce_account_validity(user)
            except DatabaseError:
                pass
            else:
                self._stamp(request)
        return response

    @staticmethod
    def _due(request):
        """本会话距上次检查是否已超过节流间隔；无 session（或首次）时总检查。"""
        session = getattr(request, "session", None)
        if session is None:
            return True
        last = session.get(_VALIDITY_CHECKED_AT_KEY)
        if not isinstance(last, (int, float)):
            return True
        return (time.time() - last) >= VALIDITY_CHECK_INTERVAL_SECONDS

    @staticmethod
    def _stamp(request):
        """记下本次检查时间；会话缺失时不写（不该出现，防御式）。"""
        session = getattr(request, "session", None)
        if session is not None:
            session[_VALIDITY_CHECKED_AT_KEY] = time.time()
