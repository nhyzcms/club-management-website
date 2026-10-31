import json
import logging
import mimetypes
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.contrib.auth import login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.signals import user_login_failed
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request

from common.policy import get_policy

from . import factors, member_lookup, stepup
from .authcode import AuthCodeError, redeem_authcode
from .deletion import AccountDeletionError, delete_account
from .email_domains import (
    EMAIL_DOMAIN_BLOCKED_MESSAGE,
    EMAIL_DOMAIN_BLOCKED_REASON,
    email_domain,
    is_allowed_email_domain,
)
from .forms import LoginForm, PasswordResetForm, PasswordResetConfirmForm, ProfileForm, ChangePasswordForm
from .queries import deleted_q, expiry_disabled_q, must_change_password_q
from .member_codes import verify_signature
from .member_roster import ClaimError, auto_bind_on_register, claim_candidates, claim_identity
from .models import (
    MemberIdentity,
    PasswordResetRequest,
    Profile,
    IdentityProof,
    UserSession,
    Verification,
    is_verified,
    verification_valid_days,
)
from .password_reset import (
    DEFAULT_RESET_PASSWORD,
    pending_request_for,
    resolve_account,
)
from .registration_guard import duplicate_message, find_duplicate
from .tokens import email_verification_token
from .devices import get_or_create_device, record_login_event
from . import login_challenge as challenges
from .validity_summary import account_validity, ack_notice
from .throttles import (
    AuthCodeRedeemThrottle,
    MemberCheckThrottle,
    MemberClaimIpThrottle,
    MemberClaimThrottle,
    MemberLookupThrottle,
    PasswordResetEmailThrottle,
    PasswordResetRequestThrottle,
    PasswordResetTargetThrottle,
    RegisterThrottle,
    ResendVerificationThrottle,
    StepUpEmailIpThrottle,
    StepUpEmailUserThrottle,
    login_blocked_response,
)
from .turnstile import passes_turnstile, turnstile_error_response
from .utils import (
    MAX_ACTIVE_SESSIONS,
    SESSION_HISTORY_LIMIT,
    record_user_session,
)
from .validity import enforce_account_validity
from .visibility import content_visibility, profile_view_for

logger = logging.getLogger(__name__)

# 登录保护（多端登录后重定义，ADR-0028）：10 分钟窗口内同一账号最多成功登录
# LOGIN_PROTECTION_MAX_LOGINS 次。放开了「第二台设备必须等 10 分钟」的单会话限制
# （三端同时登录是产品要求），仍保留对「账号密码共享 / 反复挤号」的节流。
LOGIN_PROTECTION_SECONDS = 600
LOGIN_PROTECTION_MAX_LOGINS = 5
CONTENT_LIMIT = 15  # 个人中心每个内容 tab 返回的最近条数

_EXPIRED_UNVERIFIED_MESSAGE = "本账户超过 60 日未认证，已被系统停用。请联系社长或服务器管理员处理。"


def _verification_closed_response():
    return JsonResponse(
        {"error": "认证通道已关闭", "reason": "verification_closed"},
        status=403,
    )


IDENTITY_CHOICE_KEYS = {key for key, _label in Profile.IDENTITY_CHOICES}

# 人工通道身份证明约束（#38，与自助注册原证明约束一致）
PROOF_MIN_COUNT = 1
PROOF_MAX_COUNT = 3
PROOF_MAX_BYTES = 5 * 1024 * 1024  # 单张 ≤ 5MB
PROOF_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _json_body(request):
    try:
        return json.loads(request.body)
    except json.JSONDecodeError:
        return None


def _form_errors(form):
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    for error in form.non_field_errors():
        errors.append(error)
    return errors[0] if len(errors) == 1 else errors


def _send_verification_email(user):
    """发邮箱认证邮件到 **待认证邮箱**（email 通道 identifier，非 User.email）。

    链接 = FRONTEND_URL + #/verify-email?uid=&token=。令牌绑 identifier + 通道 status
    （见 accounts.tokens）：改邮箱或认证通过后旧令牌失效。发信失败仅记日志、不抛——
    账号已建，用户可走「重发」补发，不因 SMTP 抖动回滚。无待认证邮箱则不发。
    """
    v = user.verifications.filter(channel=Verification.CHANNEL_EMAIL).first()
    if v is None or not v.identifier:
        return  # 无待认证邮箱：无可发（注册未留邮箱等情况）
    recipient = v.identifier
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    link = f"{settings.FRONTEND_URL}/#/verify-email?uid={uid}&token={token}"
    try:
        send_mail(
            subject="邮箱认证 - 南汇一中传媒社",
            message=(
                "你好！请点击下方链接完成邮箱认证：\n\n"
                f"{link}\n\n"
                "如果你没有注册过本社团账号，请忽略此邮件。"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=True,
        )
    except Exception:
        logger.exception("发送邮箱认证邮件失败: user_pk=%s", user.pk)


@require_POST
def login_view(request):
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    form = LoginForm(body)
    if not form.is_valid():
        return JsonResponse({"error": _form_errors(form)}, status=400)

    username = form.get_username()
    # 邮箱不存在时 get_username 为 None；仍用提交的用户名/邮箱作撞库计数键。
    throttle_ident = username or form.cleaned_data.get("username") or form.cleaned_data.get("email") or ""
    blocked = login_blocked_response(request, throttle_ident)
    if blocked is not None:
        return blocked

    # 用 check_password 而非 authenticate：密码正确后再区分「停用 / 未认证」，
    # 错误密码统一回 401，不泄露账号存在性与状态（防枚举）。
    candidate = User.objects.filter(username=username).first() if username else None
    if candidate is None or not candidate.check_password(form.cleaned_data["password"]):
        user_login_failed.send(
            sender=User,
            request=request,
            credentials={"username": throttle_ident},
        )
        record_login_event(request, user=candidate, status="failed")
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    # 密码正确 → 确为本人，可安全揭示账号状态（停用 / 放行）。
    # 惰性执行身份有效期（ADR-0041）：过期管理员撤销 / 超期未认证停用。
    action = enforce_account_validity(candidate)
    if action == "unverified_expired":
        return JsonResponse(
            {"error": _EXPIRED_UNVERIFIED_MESSAGE, "reason": "account_expired_unverified"},
            status=403,
        )
    if not candidate.is_active:
        # 已被 cron / 惰性执行停用的「超期未认证」账号（带 expiry_disabled_at 标记）也走专属提示。
        if Profile.objects.filter(user=candidate).filter(expiry_disabled_q()).exists():
            return JsonResponse(
                {"error": _EXPIRED_UNVERIFIED_MESSAGE, "reason": "account_expired_unverified"},
                status=403,
            )
        return JsonResponse(
            {"error": "账号已停用，请联系信息组。", "reason": "account_disabled"},
            status=403,
        )
    # 登录与认证解耦（ADR-0006 决策 6）：未认证账号可登录为访客，仅 is_active 拒停用。
    # 写操作门禁由 IsVerified 单独管（未认证能登、能读，不能写）。

    # 登录保护（ADR-0028）：10 分钟窗口内同一账号最多 5 次成功登录。
    # 单会话时代的「他方 10 分钟内不许登录」已随多端登录取消（三端必须能立刻依次登录），
    # 这里只保留对「账号密码共享 / 反复挤号」的节流；名额顶替交给 record_user_session。
    window_start = timezone.now() - timedelta(seconds=LOGIN_PROTECTION_SECONDS)
    recent_logins = list(
        UserSession.objects.filter(user=candidate, created_at__gte=window_start)
        .order_by("created_at")
        .values_list("created_at", flat=True)
    )
    if len(recent_logins) >= LOGIN_PROTECTION_MAX_LOGINS:
        retry_at = recent_logins[-LOGIN_PROTECTION_MAX_LOGINS] + timedelta(
            seconds=LOGIN_PROTECTION_SECONDS
        )
        retry_after = max(1, int((retry_at - timezone.now()).total_seconds()))
        return JsonResponse(
            {
                "error": "Login protection active",
                "reason": "login_protection",
                "retry_after": retry_after,
            },
            status=409,
        )

    previous_key = request.session.session_key

    device, is_new_device = get_or_create_device(candidate, request)
    # 陌生设备（未通过过二次验证）→ 有 2FA 就挑战；没有任何 2FA 则本次豁免放行。
    exempt = False
    if settings.LOGIN_CHALLENGE_ENABLED and device is not None and not device.is_trusted:
        methods = challenges.available_factors(candidate)
        if methods:
            challenge = challenges.create_challenge(
                candidate, device.device_id, bool(form.cleaned_data.get("remember"))
            )
            record_login_event(
                request,
                user=candidate,
                device=device,
                status="challenge",
                method="password",
                second_factor="",
                is_new_device=True,
            )
            return JsonResponse(challenges.challenge_payload(challenge), status=202)
        exempt = True

    login(request, candidate)
    if previous_key and previous_key != request.session.session_key:
        # 同一浏览器重复登录 / 换账号：旧会话行让位，别让一台设备占掉两个名额。
        UserSession.objects.filter(session_key=previous_key, revoked_at__isnull=True).update(
            revoked_at=timezone.now(),
            revoked_reason=UserSession.REVOKE_REPLACED,
            replaced_by_session_key=request.session.session_key,
        )
    # 管理员手动重置过密码 → 本次登录必须先去改密（前端据 must_change_password 跳转；
    # 会话值供 PasswordChangeRequiredMiddleware 免查库判定）。
    must_change = Profile.objects.filter(
        user=candidate,
    ).filter(must_change_password_q()).exists()
    request.session["pwd_change_required"] = must_change
    # 「记住登录」：勾选 → 持久 cookie（settings.REMEMBER_LOGIN_SECONDS = 30 天）；
    # 不勾 → set_expiry(0)，Django 视为浏览器会话 cookie（max-age 不下发，关浏览器失效）。
    request.session.set_expiry(
        settings.REMEMBER_LOGIN_SECONDS if form.cleaned_data.get("remember") else 0
    )
    record_login_event(
        request,
        user=candidate,
        device=device,
        status="success",
        method="password",
        second_factor="exempt" if exempt else "none",
        is_new_device=is_new_device,
        session_key=request.session.session_key or "",
    )
    payload = {
        "user": {"id": candidate.id, "username": candidate.username, "email": candidate.email},
        "must_change_password": must_change,
    }
    if exempt:
        # 本次豁免不等于信任：设备仍陌生，下次登录仍会要求；前端提示尽快绑定。
        payload["must_bind_2fa"] = True
    return JsonResponse(payload)



@ensure_csrf_cookie
def csrf_token_view(request):
    """显式下发 csrftoken cookie。

    供前端 SPA 启动时请求一次。开发态 webpack 直接服务模板、不经 Django 渲染，
    无法靠 {% csrf_token %} 下发 cookie；此端点把 cookie 下发与 HTML 渲染解耦，
    避免全新访客的匿名 POST（登录、找回密码等）被 403。
    """
    return JsonResponse({"detail": "CSRF cookie set"})


@require_POST
@login_required
def logout_view(request):
    """退出当前设备（只下线本机，其余设备保持登录态，ADR-0028）。"""
    session_key = request.session.session_key
    auth_logout(request)
    if session_key:
        UserSession.objects.filter(session_key=session_key).update(
            revoked_at=timezone.now(), revoked_reason=UserSession.REVOKE_LOGOUT,
        )
    return JsonResponse({"message": "Logged out"})


@require_GET
@login_required
def verification_status_view(request):
    """账号认证状态（#36）：总 is_verified + 各通道当前状态，数据驱动面板铺卡。

    每个已定义通道一卡，按 CHANNELS 序。无 Verification 行的通道 status="none"（前端映射
    「未绑定 / 未提交」；后台委任 none 不铺卡）。通道对象键集与前端 VerificationPanel 契约
    （见契约测试）。``is_verified`` 已含有效期判定（ADR-0041），键集契约保持不变。

    单一认证路径：账号已认证（任一通道 approved 且未过期）后，其余通道一律返回派生状态
    ``not_required``（「无需再次认证」），前端据此收掉表单。该状态**不落库**——认证过期后
    ``is_verified`` 回落为 False，通道自动恢复真实状态、可重新申请，无需数据迁移或补偿任务。
    """
    user = request.user
    rows = {v.channel: v for v in user.verifications.all()}
    now = timezone.now()
    active_channels = {
        v.channel
        for v in rows.values()
        if v.status == Verification.STATUS_APPROVED
        and (v.expires_at is None or v.expires_at > now)
    }
    verified = is_verified(user)
    channels = []
    for channel, _label in Verification.CHANNELS:
        v = rows.get(channel)
        status = v.status if v else "none"
        # 已认证时，除生效中的那条 approved 通道外都收口为「无需再次认证」。
        # active_channels 非空是保险：万一 is_verified 与本次查询不一致，不要把每张卡都锁死。
        if verified and active_channels and channel not in active_channels:
            status = Verification.STATUS_NOT_REQUIRED
        channels.append({
            "channel": channel,
            "status": status,
            "identifier": v.identifier if v else "",
            "verified_at": v.verified_at.isoformat() if v and v.verified_at else None,
        })
    return JsonResponse({"is_verified": verified, "channels": channels})


@require_GET
def validity_summary_view(request):
    """账号有效期快照（ADR-0041）：状态 / 到期时间 / 剩余天数 / 一次性提示键。

    只读、无副作用；前端在注册后、认证通过后与每次进入站点时各取一次，据
    ``notice_pending`` 决定是否弹「有效期说明」。

    匿名访问返回 **401 JSON**（而不是 ``@login_required`` 的 302）：本端点只被 XHR
    调用，跳转到 ``/login/`` 会让匿名访客多下载一份 SPA HTML；前端把 401 当「未登录」静默。
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "未登录。"}, status=401)
    return JsonResponse(account_validity(request.user))


@require_POST
@login_required
def validity_ack_view(request):
    """标记有效期提示已读：body ``{"key": "..."}``。

    键必须是**当前**快照键（状态或到期时间已变则拒绝），防止客户端拿旧键把新提示
    一并吞掉。返回 ``{"acknowledged": bool}``。
    """
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    key = (body.get("key") or "").strip()
    if not key:
        return JsonResponse({"error": "缺少 key。"}, status=400)
    return JsonResponse({"acknowledged": ack_notice(request.user, key)})


@require_POST
@login_required
def verification_email_bind_view(request):
    """邮箱通道绑定 / 重发 / 换邮（面板动作，#37 / ADR-0006）。

    统一为「email 通道置 pending + identifier=待认证地址 + 发信」，``User.email`` 不动（待认证邮箱
    不住此）——认证通过才晋升（见 verify_email_view）。故：
      - 首次绑定 / 重发同邮箱 → 建或刷新 pending 行并发信；
      - 换邮箱（含已认证旧邮箱）→ 回 pending(identifier=新)，旧 User.email 在新认证前仍有效；
      - 已认证且未过期同邮箱再绑 → no-op（不降级）；过期则回落重新认证。
    绑定时校验邮箱唯一（User.email 或他人 pending identifier）与**后缀白名单**（ADR-0023：
    只拦新地址，既有同址重发 / 复绑按祖父条款放行）。
    """
    if not get_policy().verification_enabled:
        return _verification_closed_response()
    if not ResendVerificationThrottle().allow_request(request, None):
        return JsonResponse({"error": "请求过于频繁，请稍后再试。"}, status=429)

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    email = (body.get("email") or "").strip().lower()
    if not email:
        return JsonResponse({"error": "请输入邮箱。"}, status=400)
    try:
        EmailValidator()(email)
    except ValidationError:
        return JsonResponse({"error": "邮箱格式不正确"}, status=400)

    user = request.user
    existing = user.verifications.filter(channel=Verification.CHANNEL_EMAIL).first()
    # 换绑（真正改地址）需安全验证（ADR-0026）；首次绑定 / 同址重发不拦（否则新用户无法开邮箱）。
    same_address = existing is not None and existing.identifier == email
    if (
        not same_address
        and (bool((user.email or "").strip()) or existing is not None)
        and not stepup.grant_from_request(request, "change_email")
    ):
        return stepup.stepup_required_response("change_email")
    # 已认证且未过期同邮箱再绑 → no-op（不降级为 pending、不重发）
    if (
        existing is not None
        and existing.status == Verification.STATUS_APPROVED
        and existing.identifier == email
        and (existing.expires_at is None or existing.expires_at > timezone.now())
    ):
        return JsonResponse({"message": "该邮箱已认证。"})

    # 后缀白名单（ADR-0023）：只拦「新地址」；既有同址（重发 / 复绑，含白名单上线前留下的
    # 非白名单地址）放行——不回溯旧数据，否则这批人会被卡在认证中途。
    same_identifier = existing is not None and existing.identifier == email
    if not same_identifier and not is_allowed_email_domain(email):
        return _email_domain_blocked_response(email)

    # 唯一性：不可绑他账号有效持有的邮箱（已认证 User.email 或他人 pending identifier）
    if _email_taken(email, exclude_user=user):
        return JsonResponse({"error": "该邮箱已被占用"}, status=400)

    if existing is None:
        Verification.objects.create(
            user=user, channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING, identifier=email,
        )
    else:
        # 换邮箱 / 过期重验：回 pending + 新 identifier；旧 verified_at/by/expires_at 随之失效
        existing.status = Verification.STATUS_PENDING
        existing.identifier = email
        existing.verified_at = None
        existing.verified_by = None
        existing.expires_at = None
        existing.save(update_fields=["status", "identifier", "verified_at", "verified_by", "expires_at"])

    _send_verification_email(user)
    return JsonResponse({"message": "认证邮件已发送，请查收。"})


@require_POST
@login_required
def verification_manual_submit_view(request):
    """人工审批通道：提交身份证明（#38 / ADR-0006）。

    multipart：real_name + identity（在校生 / 外校生 / 毕业生 / 家长 / 教师）+ proof_files[]
    （1~3 张 jpg/png/webp，单张 ≤5MB）。把 manual 通道置 pending + IdentityProof 累加（永久
    留底，审核通过后亦不删）。仅当 manual 当前 none / rejected / 已过期 可提交（pending 审核中、
    已通过且未过期 不可重复）。real_name / identity 写入 Profile（人工审核需知真实身份）。
    """
    if not get_policy().verification_enabled:
        return _verification_closed_response()
    real_name = (request.POST.get("real_name") or "").strip()
    identity = (request.POST.get("identity") or "").strip()
    proof_files = request.FILES.getlist("proof_files")

    errors = []
    if not real_name:
        errors.append("请填写真实姓名")
    if identity not in IDENTITY_CHOICE_KEYS:
        errors.append("请选择有效身份")
    if len(proof_files) < PROOF_MIN_COUNT:
        errors.append(f"请至少上传 {PROOF_MIN_COUNT} 张身份证明照片")
    elif len(proof_files) > PROOF_MAX_COUNT:
        errors.append(f"身份证明最多 {PROOF_MAX_COUNT} 张")
    for f in proof_files:
        if f.size > PROOF_MAX_BYTES:
            errors.append(f"证明材料「{f.name}」超过 5MB 上限")
        if f.content_type not in PROOF_ALLOWED_TYPES:
            errors.append(f"证明材料「{f.name}」格式不支持（仅 JPG / PNG / WebP）")
    if errors:
        return JsonResponse({"error": errors[0] if len(errors) == 1 else errors}, status=400)

    user = request.user
    existing = user.verifications.filter(channel=Verification.CHANNEL_MANUAL).first()
    # 审核中 → 不可重复提交；已通过且未过期 → 无需重交；驳回 / 已过期 → 允许重交（重新认证）
    if existing is not None and existing.status == Verification.STATUS_PENDING:
        return JsonResponse({"error": "当前审核中，请勿重复提交"}, status=400)
    if (
        existing is not None
        and existing.status == Verification.STATUS_APPROVED
        and (existing.expires_at is None or existing.expires_at > timezone.now())
    ):
        return JsonResponse({"error": "当前已通过认证，无需重复提交"}, status=400)

    with transaction.atomic():
        # none → 建 pending；rejected（重交）/ 已过期（重新认证）→ 回 pending + 清旧审核痕迹
        Verification.objects.update_or_create(
            user=user, channel=Verification.CHANNEL_MANUAL,
            defaults={
                "status": Verification.STATUS_PENDING,
                "verified_at": None,
                "verified_by": None,
                "expires_at": None,
            },
        )
        for f in proof_files:
            IdentityProof.objects.create(user=user, file=f)
        profile = _get_or_create_profile(user)
        profile.real_name = real_name
        profile.identity = identity
        profile.save(update_fields=["real_name", "identity"])

    from messaging.services import notify_perm  # 局部导入：避免潜在循环依赖

    notify_perm(
        "review",
        "identity_submitted",
        "accounts.can_review_identity",
        actor=user,
        payload={
            "type": "identity",
            "id": user.pk,
            "username": user.username,
            "url": "/reviews",
        },
    )
    return JsonResponse({"message": "身份证明已提交，等待管理员审核。"})


@require_POST
@login_required
def verification_authcode_redeem_view(request):
    """认证码通道：兑换认证码（ADR-0020）。

    码由持 accounts.add_authcode 的用户在 Django 后台生成、线下分发；成员在此兑换，
    即时通过（无 pending、无人工环节）。无效 / 过期 / 用尽 / 吊销计入按账号节流
    （只计失败）；成功不占额度。ADR-0041：已通过且未过期的账号不可再兑换；认证过期
    后允许重新兑换（重新认证）。
    """
    if not get_policy().verification_enabled:
        return _verification_closed_response()

    throttle = AuthCodeRedeemThrottle()
    if throttle.is_blocked(request):
        return JsonResponse({"error": "请求过于频繁，请稍后再试。"}, status=429)

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    code = (body.get("code") or "").strip()
    if not code:
        return JsonResponse({"error": "请输入认证码。"}, status=400)

    if is_verified(request.user):
        return JsonResponse({"error": "账号已完成认证，无需使用认证码。"}, status=400)

    try:
        redeem_authcode(request.user, code)
    except AuthCodeError as exc:
        throttle.allow_request(request, None)  # 只计失败：成功不占额度
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({"message": "认证码认证通过，账号已完成认证。"})


def _member_identity_payload(row: MemberIdentity) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "cohort": row.cohort,
        "code": row.code,
        "card_no": row.card_no,
        "status": row.status,
        "bound_at": row.bound_at.isoformat() if row.bound_at else None,
    }


@require_GET
@login_required
def member_identity_view(request):
    """社员身份（ADR-0025）：本人绑定状态 + 可认领候选。

    候选 = 「未绑定」且姓名与本人真实姓名（归一后）一致的名册行；
    认领开关关闭 / 已绑定时不返回候选。
    """
    policy = get_policy()
    bound = MemberIdentity.objects.filter(user=request.user).first()
    candidates = []
    if policy.member_claim_enabled and bound is None:
        candidates = claim_candidates(request.user)
    return JsonResponse({
        "enabled": policy.member_claim_enabled,
        "bound": _member_identity_payload(bound) if bound is not None else None,
        "candidates": [
            {"id": row.id, "name": row.name, "cohort": row.cohort}
            for row in candidates
        ],
    })


@require_POST
@login_required
def member_claim_view(request):
    """自助认领（ADR-0025）：选一条未绑定身份 + 手机号后四位校验即绑定。

    失败（手机号不对 / 已绑定等）按账号与 IP 双通道节流（只计失败）；
    服务端强制「账号真实姓名 == 名册行姓名」，不信任前端候选列表。
    """
    if not get_policy().member_claim_enabled:
        return JsonResponse({"error": "自助认领已关闭。", "reason": "claim_closed"}, status=403)

    user_throttle = MemberClaimThrottle()
    ip_throttle = MemberClaimIpThrottle()
    if user_throttle.is_blocked(request) or ip_throttle.is_blocked(request):
        return JsonResponse({"error": "请求过于频繁，请稍后再试。"}, status=429)

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    phone_last4 = (body.get("phone_last4") or "").strip()
    try:
        identity_id = int(body.get("identity_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "请选择身份并输入手机号后四位。"}, status=400)
    if not phone_last4:
        return JsonResponse({"error": "请选择身份并输入手机号后四位。"}, status=400)

    try:
        row = claim_identity(request.user, identity_id, phone_last4)
    except ClaimError as exc:
        user_throttle.allow_request(request, None)  # 只计失败：成功不占额度
        ip_throttle.allow_request(request, None)
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({
        "message": "认领成功。",
        "member": _member_identity_payload(row),
    })


@require_GET
def member_check_view(request):
    """扫码校验（公开，ADR-0025）：``?c=<识别码>&s=<签名>``。

    签名不符 / 码不存在一律 404（语义不可区分，防枚举）；命中返回最小公开字段：
    姓名、届数、组别、状态、头像（可选）。电话 / 学号 / 邮箱绝不出现。
    """
    throttle = MemberCheckThrottle()
    if not throttle.allow_request(request, None):
        return JsonResponse({"error": "请求过于频繁，请稍后再试。"}, status=429)

    code = (request.GET.get("c") or "").strip()
    sig = (request.GET.get("s") or "").strip()
    not_found = JsonResponse({"found": False}, status=404)
    if not verify_signature(code, sig):
        return not_found

    row = MemberIdentity.objects.filter(code=code).first()
    if row is None:
        return not_found

    return JsonResponse({"found": True, **member_lookup.public_member_payload(row)})


@require_http_methods(["GET", "POST"])
def member_lookup_view(request):
    """社员查询（公开）：按真实姓名 / 社员编号查，结果与扫码校验页同源同形。

    - ``GET``：只读当前额度（不计数），前端用它显示「今日还可查 N 次」。
    - ``POST`` ``{"q": "..."}``：查一次并**先扣额度**（未命中同样计数，防枚举遍历）。

    额度按查询者身份分档（未登录 3 / 未认证 10 / 已认证非社员 20 / 社员·教师·管理员不限），
    见 :mod:`accounts.member_lookup`。超限返回 429 + 额度快照，前端据此提示。
    """
    if request.method == "GET":
        return JsonResponse({"quota": member_lookup.quota_snapshot(request)})

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    query = str(body.get("q") or "").strip()
    if not query:
        return JsonResponse({"error": "请输入真实姓名或社员编号。"}, status=400)

    # 12 位条码载荷：签名即证明，不消耗 24 小时额度（现场连扫几十张工牌），
    # 防枚举改由 IP 频控兜底——签名空间 10^6，配上 300 次/时 已无可行遍历路径。
    if member_lookup.is_signed_payload(query):
        throttle = MemberLookupThrottle()
        if not throttle.allow_request(request, None):
            return JsonResponse({"error": "请求过于频繁，请稍后再试。"}, status=429)
        rows = member_lookup.resolve_signed_payload(query)
        return JsonResponse({
            "found": bool(rows),
            "results": [member_lookup.public_member_payload(row) for row in rows],
            "quota": member_lookup.quota_snapshot(request),
        })

    allowed, quota = member_lookup.consume(request)
    if not allowed:
        return JsonResponse(
            {
                "error": (
                    f"查询次数已达上限（每 {member_lookup.WINDOW_HOURS} 小时最多 "
                    f"{quota['limit']} 次），请稍后再试。"
                ),
                "quota": quota,
                "retry_after": member_lookup.retry_after(quota),
            },
            status=429,
        )

    rows = member_lookup.search_members(query)
    return JsonResponse({
        "found": bool(rows),
        "results": [member_lookup.public_member_payload(row) for row in rows],
        "quota": quota,
    })


# ---- 安全验证（Step-up，ADR-0026）----


def _mask_email(address: str) -> str:
    """邮箱打码：本地部分保留前 2 位（user@x.com → us***@x.com）。"""
    local, _, domain = (address or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:2]}***@{domain}"


@require_GET
@login_required
def stepup_status_view(request):
    """验证方式总览：可用因子（按 scope 过滤）+ 邮箱地址/冷却。

    ``scope`` 由前端带上（例 ?scope=manage_totp），用于过滤「该操作不允许使用」的因子；
    新增验证方式只需在 accounts/factors.py 注册，这里自动随之变化。
    """
    user = request.user
    scope = (request.GET.get("scope") or "").strip()
    questions = user.security_questions.all()
    return JsonResponse({
        "scopes": stepup.SCOPES,
        "factors": [
            {
                "key": factor.key,
                "label": factor.label,
                "hint": factor.hint,
                "sends_code": factor.sends_code,
            }
            for factor in factors.for_user(user, scope)
        ],
        "email": {
            "available": stepup.email_available(user),
            "address": _mask_email(user.email) if stepup.email_available(user) else "",
            "cooldown_remaining": stepup.email_cooldown_remaining(user),
        },
        "questions": {
            "configured": questions.exists(),
            "count": questions.count(),
        },
        "grant_ttl": stepup.GRANT_TTL_SECONDS,
    })


@require_POST
@login_required
def stepup_email_send_view(request):
    """发送安全验证码：60 秒冷却 + 账号 / IP 双通道小时上限（策略）。"""
    user = request.user
    if not stepup.email_available(user):
        return JsonResponse(
            {"error": "当前账号没有已认证邮箱，无法使用邮箱验证码。", "reason": "email_unavailable"},
            status=400,
        )
    remaining = stepup.email_cooldown_remaining(user)
    if remaining > 0:
        return JsonResponse(
            {"error": f"发送太频繁，请 {remaining} 秒后再试。", "reason": "cooldown", "retry_after": remaining},
            status=429,
        )
    if not StepUpEmailUserThrottle().allow_request(request, None) or not StepUpEmailIpThrottle().allow_request(request, None):
        return JsonResponse({"error": "请求过于频繁，请稍后再试。"}, status=429)
    try:
        stepup.send_email_code(user)
    except stepup.StepUpError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        logger.exception("发送安全验证码失败：user_pk=%s", user.pk)
        return JsonResponse({"error": "邮件发送失败，请稍后重试。"}, status=500)
    return JsonResponse({"message": "验证码已发送，请查收邮件。"})


@require_POST
@login_required
def stepup_verify_view(request):
    """验证：{method, scope, code / question_id+answer} → 签发 grant（TTL 10 分钟、同 scope 复用）。"""
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    scope = (body.get("scope") or "").strip()
    method = (body.get("method") or "").strip()
    if scope not in stepup.SCOPES:
        return JsonResponse({"error": "未知的验证作用域。"}, status=400)

    factor = factors.get(method)
    if factor is None:
        return JsonResponse({"error": "未知的验证方式。"}, status=400)
    if scope in factor.excluded_scopes:
        return JsonResponse(
            {"error": f"「{factor.label}」不能用于当前操作，请换一种方式。"}, status=400
        )

    user = request.user
    if not factor.available(user):
        return JsonResponse({"error": f"「{factor.label}」当前不可用。"}, status=400)
    try:
        factor.verify(user, body)
    except (stepup.StepUpError, factors.FactorError) as exc:
        stepup.record_event(user, scope, factor.key, "fail", request)
        return JsonResponse({"error": str(exc)}, status=400)

    stepup.record_event(user, scope, factor.key, "ok", request)
    return JsonResponse({
        "message": "验证通过。",
        "grant": stepup.issue_grant(user, scope),
        "expires_in": stepup.GRANT_TTL_SECONDS,
    })


@login_required
def stepup_questions_view(request):
    """GET：题库 + 本人已设（只出题干）；POST：设置 / 更换 / 清除（首设＝密码确认，之后＝grant）。"""
    user = request.user
    if request.method == "GET":
        return JsonResponse({
            "bank": stepup.question_bank(),
            "mine": [
                {"id": q.id, "key": q.question_key, "text": q.question_text}
                for q in user.security_questions.all()
            ],
        })
    if request.method != "POST":
        return JsonResponse({"error": "Method Not Allowed"}, status=405)

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    items = body.get("items")
    if not isinstance(items, list):
        return JsonResponse({"error": "items 须为数组。"}, status=400)

    if not user.security_questions.exists():
        # 首次设置＝重输登录密码（防「偷到会话但没有密码」的人自设验证方式再改密码）
        password = body.get("password") or ""
        if not password or not user.check_password(password):
            return JsonResponse(
                {"error": "请输入当前登录密码以确认身份。", "reason": "password_required"},
                status=400,
            )
    elif not stepup.grant_from_request(request, "manage_questions"):
        return stepup.stepup_required_response("manage_questions")

    try:
        stepup.set_security_questions(user, items)
    except stepup.StepUpError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"message": "安全问题已更新。", "count": user.security_questions.count()})


@require_GET
@login_required
def stepup_events_view(request):
    """本人最近的安全验证记录（轻量审计，倒序 20 条）。"""
    rows = request.user.stepup_events.all()[:20]
    return JsonResponse({"results": [
        {
            "scope": row.scope,
            "scope_label": stepup.SCOPES.get(row.scope, row.scope),
            "method": row.method,
            "result": row.result,
            "ip": row.ip,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]})


@login_required
def me_view(request):
    profile = _get_or_create_profile(request.user)
    return JsonResponse(_profile_response(request.user, profile))


@require_GET
@login_required
def sessions_view(request):
    """登录设备（多端登录，ADR-0028）：本人最近的登录记录 + 名额占用。

    ``revoked_at IS NULL`` 为在线设备（最多 ``max_active`` 台），其余是历史记录
    （``revoked_reason`` 说明是被顶替、手动下线还是主动退出）。``is_this_device``
    由服务端比对当前请求的 session key 得出，前端据此标「本机」。
    数据按用户裁剪到 ``SESSION_HISTORY_LIMIT`` 条，分页沿用同一上限做单页，
    返回完整信封（count/next/previous/results）供前端统一消费。
    """
    qs = UserSession.objects.filter(user=request.user).order_by("-created_at", "-id")
    paginator = PageNumberPagination()
    paginator.page_size = SESSION_HISTORY_LIMIT
    page = paginator.paginate_queryset(qs, Request(request))  # 单页（存储层已裁剪）
    current_key = request.session.session_key
    return JsonResponse({
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "max_active": MAX_ACTIVE_SESSIONS,
        "active_count": _active_sessions(request.user).count(),
        "results": [
            {
                "id": r.id, # type: ignore
                "device_name": r.device_name,
                "device_type": r.device_type,
                "client_kind": r.client_kind,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat(),
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
                "is_active": r.is_active,
                "is_this_device": bool(current_key) and r.session_key == current_key,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                "revoked_reason": r.revoked_reason,
            }
            for r in page
        ],
    })


def _active_sessions(user):
    return UserSession.objects.filter(user=user, revoked_at__isnull=True)


@require_POST
@login_required
def session_revoke_view(request, session_id):
    """在个人中心下线一台设备（只限本人的记录）。

    只写 ``revoked_at``、不删 Django Session：被下线设备的下一次请求会拿到
    401 ``session_superseded`` + ``revoked_reason=manual``，前端弹「该设备已被下线」。
    下线本机等价于退出登录。
    """
    row = UserSession.objects.filter(id=session_id, user=request.user).first()
    if row is None:
        return JsonResponse({"error": "登录记录不存在"}, status=404)
    changed = False
    if row.revoked_at is None:
        row.revoked_at = timezone.now()
        row.revoked_reason = UserSession.REVOKE_MANUAL
        row.save(update_fields=["revoked_at", "revoked_reason"])
        changed = True
    is_this_device = bool(request.session.session_key) and (
        row.session_key == request.session.session_key
    )
    if changed and is_this_device:
        auth_logout(request)
    return JsonResponse({
        "revoked": changed,
        "was_current": is_this_device,
        "active_count": _active_sessions(request.user).count(),
        "max_active": MAX_ACTIVE_SESSIONS,
    })


@require_POST
@login_required
def sessions_revoke_others_view(request):
    """下线其他所有设备（保留本机）。"""
    updated = (
        _active_sessions(request.user)
        .exclude(session_key=request.session.session_key)
        .update(revoked_at=timezone.now(), revoked_reason=UserSession.REVOKE_MANUAL)
    )
    return JsonResponse({
        "revoked": updated,
        "active_count": _active_sessions(request.user).count(),
        "max_active": MAX_ACTIVE_SESSIONS,
    })


@require_POST
def password_reset_view(request):
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # 每 IP / 每邮箱双维度限流（审计 M-3）：同步 SMTP 不能被匿名刷成邮件轰炸。
    if not PasswordResetEmailThrottle().allow_request(request, None):
        return JsonResponse(
            {"error": "请求过于频繁，请稍后再试。", "reason": "password_reset_throttled"},
            status=429,
        )
    request._password_reset_email = (body.get("email") or "").strip().lower()
    if not PasswordResetTargetThrottle().allow_request(request, None):
        return JsonResponse(
            {"error": "该邮箱请求过于频繁，请稍后再试。", "reason": "password_reset_throttled"},
            status=429,
        )

    form = PasswordResetForm(body)
    if not form.is_valid():
        return JsonResponse({"error": _form_errors(form)}, status=400)

    if not passes_turnstile(request, body.get("turnstile_token") or ""):
        return turnstile_error_response()

    email = form.cleaned_data["email"]
    for user in User.objects.filter(email=email):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        send_mail(
            subject="Password Reset",
            message=f"{settings.FRONTEND_URL}/#/reset-password?uid={uid}&token={token}",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[email],
            fail_silently=True,
        )

    return JsonResponse({"message": "If an account with that email exists, a reset link has been sent."})


@require_POST
def password_reset_confirm_view(request):
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    form = PasswordResetConfirmForm(body)
    if not form.is_valid():
        return JsonResponse({"error": _form_errors(form)}, status=400)

    try:
        user_id = force_str(urlsafe_base64_decode(form.cleaned_data["uid"]))
        user = User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "Invalid reset link"}, status=400)

    if not default_token_generator.check_token(user, form.cleaned_data["token"]):
        return JsonResponse({"error": "Invalid or expired token"}, status=400)

    user.set_password(form.cleaned_data["new_password"])
    user.save()
    return JsonResponse({"message": "Password has been reset successfully."})


@require_POST
def password_reset_request_view(request):
    """忘记密码 → 向管理员申请手动重置（匿名，multipart）。

    字段：``account``（用户名 / 邮箱 / 唯一真实姓名）、``contact``（可选）、
    ``note``（可选）、``proof``（身份证明 1 张，≤5MB，JPG/PNG/WebP）、
    ``turnstile_token``（启用时必填）。

    证明落私有存储；管理员在审核台核对后批准（见 accounts.password_reset）。
    """
    if not PasswordResetRequestThrottle().allow_request(request, None):
        return JsonResponse(
            {"error": "提交过于频繁，请稍后再试。", "reason": "request_throttled"},
            status=429,
        )

    if not passes_turnstile(request, request.POST.get("turnstile_token") or ""):
        return turnstile_error_response()

    identifier = (request.POST.get("account") or "").strip()
    contact = (request.POST.get("contact") or "").strip()[:254]
    note = (request.POST.get("note") or "").strip()[:2000]
    proof = request.FILES.get("proof")

    errors = []
    if not identifier:
        errors.append("请填写用户名或邮箱")
    if proof is None:
        errors.append("请上传身份证明（学生证/校牌）")
    else:
        if proof.size > PROOF_MAX_BYTES:
            errors.append("身份证明不能超过 5MB")
        if proof.content_type not in PROOF_ALLOWED_TYPES:
            errors.append("身份证明仅支持 JPG / PNG / WebP 格式")
    if errors:
        return JsonResponse({"error": errors[0] if len(errors) == 1 else errors}, status=400)

    user, why = resolve_account(identifier)
    if user is None:
        if why == "ambiguous":
            return JsonResponse(
                {
                    "error": "该真实姓名对应多个账号，请改填用户名或邮箱。",
                    "reason": "account_ambiguous",
                },
                status=400,
            )
        return JsonResponse(
            {"error": "未找到该账号，请检查用户名 / 邮箱是否填写正确。", "reason": "account_not_found"},
            status=404,
        )

    if Profile.objects.filter(user=user).filter(deleted_q()).exists():
        return JsonResponse(
            {"error": "该账号已注销，无法重置密码。如有疑问请联系信息组。", "reason": "account_deleted"},
            status=400,
        )
    if not user.is_active:
        return JsonResponse(
            {"error": "该账号已停用，请联系信息组。", "reason": "account_disabled"},
            status=400,
        )
    if pending_request_for(user) is not None:
        return JsonResponse(
            {"error": "该账号已有待处理的申请，请耐心等待管理员审核。", "reason": "request_pending"},
            status=409,
        )

    reset_request = PasswordResetRequest.objects.create(
        user=user, identifier=identifier, contact=contact, note=note, proof=proof,
    )

    from messaging.services import notify_perm  # 局部导入：避免潜在循环依赖

    notify_perm(
        "review",
        "password_reset_requested",
        "accounts.review_password_reset",
        payload={
            "type": "password_reset",
            "id": reset_request.pk,
            "username": user.username,
            "url": "/reviews",
        },
    )
    return JsonResponse(
        {"message": "申请已提交。管理员核对身份证明后会重置密码，请留意站内通知。"},
        status=201,
    )


@require_GET
def password_reset_proof_file_view(request, pk):
    """密码重置申请的身份证明鉴权下载：仅申请人本人或持审批权者可读。"""
    reset_request = get_object_or_404(PasswordResetRequest, pk=pk)
    user = request.user
    if not user.is_authenticated:
        return HttpResponseForbidden("请先登录。")
    if reset_request.user_id != user.pk and not user.has_perm("accounts.review_password_reset"):
        return HttpResponseForbidden("无权访问该身份证明。")

    if not reset_request.proof or not reset_request.proof.storage.exists(reset_request.proof.name):
        raise Http404("证明文件不存在")

    content_type, _ = mimetypes.guess_type(reset_request.proof.name)
    return FileResponse(
        reset_request.proof.open("rb"),
        content_type=content_type or "image/jpeg",
    )


@require_POST
def register_view(request):
    """注册（ADR-0006，2026-09 修订）：建登录身份（用户名 + 密码 + Turnstile）+ 真实姓名 / 身份（必填）。

    注册↔认证分离：邮箱 / 身份证明仍挪在认证面板；但 real_name / identity 为注册必填，
    写入 Profile（identity 须合法枚举）。新号无 Verification 行 ⇒ 未认证（访客）。
    若提供邮箱：须过**后缀白名单**（ADR-0023），再建 email 通道 pending（identifier=待认证地址）
    并发认证信，``User.email`` 保持空（待认证邮箱不住 User.email）——认证通过才晋升
    （见 verify_email_view）。

    2026-10-23（ADR-0025 增补）：在校生 / 毕业生可选填「校牌号」（``card_no``），
    先存 ``Profile.card_no``，并尝试按「姓名 + 校牌号」唯一命中名册行直接绑定。
    """
    if not get_policy().registration_enabled:
        return JsonResponse(
            {"error": "当前未开放注册。", "reason": "registration_closed"},
            status=403,
        )
    # 限流优先：挡机器刷号（在所有校验之前）。
    if not RegisterThrottle().allow_request(request, None):
        return JsonResponse({"error": "注册请求过于频繁，请稍后再试。"}, status=429)

    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""
    password2 = request.POST.get("password2") or ""
    real_name = (request.POST.get("real_name") or "").strip()
    identity = (request.POST.get("identity") or "").strip()
    card_no = (request.POST.get("card_no") or "").strip()
    email = (request.POST.get("email") or "").strip().lower()  # 邮箱大小写不敏感：归一化小写
    turnstile_token = request.POST.get("turnstile_token") or ""

    # 邮箱后缀白名单（ADR-0023）：不支持的域名立即拒绝（带专属 reason，前端弹窗提示换邮箱）。
    if email and not is_allowed_email_domain(email):
        return _email_domain_blocked_response(email)

    errors = []

    if not username:
        errors.append("用户名不能为空")
    if not password:
        errors.append("密码不能为空")
    if password != password2:
        errors.append("两次输入的密码不一致")
    if password:
        try:
            validate_password(password)
        except ValidationError as e:
            errors.extend(e.messages)

    # 真实姓名 / 身份：注册页必填（identity 须合法枚举）。
    if not real_name:
        errors.append("真实姓名不能为空")
    if not identity:
        errors.append("请选择身份")
    elif identity not in IDENTITY_CHOICE_KEYS:
        errors.append("请选择有效身份")

    # 校牌号（ADR-0025 2026-10-23 增补）：只有在校生 / 毕业生登记，其余身份忽略；
    # 选填——没填不影响注册，填了先存 Profile，与名册行 MemberIdentity.card_no 是同一个值。
    if identity not in Profile.CARD_NO_IDENTITIES:
        card_no = ""
    elif len(card_no) > 20:
        errors.append("校牌号过长（最多 20 个字符）")

    # 邮箱可选；填了须格式合法。唯一性统一走下面的「三条件查重」。
    if email:
        try:
            EmailValidator()(email)
        except ValidationError:
            errors.append("邮箱格式不正确")

    if errors:
        return JsonResponse({"error": errors[0] if len(errors) == 1 else errors}, status=400)

    # 注册查重（2026-10）：用户名 / 邮箱各自唯一；真实姓名**不单独**判重，
    # 只有「姓名 + 校牌号」同时一致才视为同一账户（同名学生可以各自注册）。
    # 命中即引导回登录（见 accounts.registration_guard）。
    duplicate = find_duplicate(
        username=username, real_name=real_name, card_no=card_no, email=email,
    )
    if duplicate is not None:
        return JsonResponse(
            {
                "error": duplicate_message(duplicate),
                "reason": "account_deleted" if duplicate.deleted else "account_exists",
                "field": duplicate.field,
            },
            status=409,
        )

    # Turnstile：两项密钥都空则关闭并放行；启用时校验失败拒注册。
    if not passes_turnstile(request, turnstile_token):
        return turnstile_error_response()

    started_email = False
    try:
        with transaction.atomic():
            # User.email 只装已认证邮箱：注册阶段留空；邮箱认证通过才晋升写入。
            user = User.objects.create_user(
                username=username, email="", password=password, is_active=True
            )
            Profile.objects.create(user=user, real_name=real_name, identity=identity, card_no=card_no)
            if email and get_policy().verification_enabled:
                Verification.objects.create(
                    user=user, channel=Verification.CHANNEL_EMAIL,
                    status=Verification.STATUS_PENDING, identifier=email,
                )
                started_email = True
    except Exception:
        logger.exception("注册建号失败: username=%s", username)
        return JsonResponse({"error": "注册失败，请稍后重试。"}, status=500)

    if started_email:
        _send_verification_email(user)

    # 注册即匹配（ADR-0025 2026-10-23 增补）：姓名 + 校牌号都与名册一致且唯一 → 直接绑定；
    # 没命中不报错（名册可能还没导入），Profile.card_no 留待导入时写回名册行。
    if card_no:
        try:
            auto_bind_on_register(user, user.profile)
        except Exception:  # 绑定失败不能拖垮注册（资料已经落库，可稍后认领）
            logger.exception("注册自动绑定社员身份失败: username=%s", username)

    # 注册即登录（ADR-0025）：认领等注册后置步骤需要在登录态下完成。
    # 会话记录由 user_logged_in 信号统一写 UserSession（accounts/signals.py）。
    login(request, user)

    return JsonResponse(
        {
            "message": "注册成功。" + ("请查收邮件完成邮箱认证。" if started_email else ""),
            "user": {"id": user.id, "username": user.username},
            "logged_in": True,
        },
        status=201,
    )


@require_GET
def verify_email_view(request):
    """邮箱认证：GET /auth/verify-email/?uid=&token= → email 通道 approved + 晋升 User.email。

    令牌绑 identifier + 通道 status（见 tokens）：改待认证邮箱或认证通过后旧令牌失效。
    认证通过：identifier 晋升写入 User.email（绑定邮箱生效，可用邮箱登录 / 重置密码）。
    ADR-0041：通过时设 expires_at = 通过日 + 认证有效期。
    不校验后缀白名单（ADR-0023 决策 4）：令牌已限定为既有 pending 地址，落地即完成该地址的认证。
    """
    if not get_policy().verification_enabled:
        return _verification_closed_response()
    user = _user_from_uid(request.GET.get("uid", ""))
    token = request.GET.get("token", "")
    if user is None or not email_verification_token.check_token(user, token):
        return JsonResponse({"error": "认证链接无效或已过期。", "reason": "invalid"}, status=400)

    v = user.verifications.filter(channel=Verification.CHANNEL_EMAIL).first()
    if v is None or not v.identifier:
        return JsonResponse({"error": "认证链接无效或已过期。", "reason": "invalid"}, status=400)

    # approved：identifier 晋升 → User.email（绑定邮箱生效）；令牌随 status 翻转失效，不可重放。
    if v.status != Verification.STATUS_APPROVED:
        v.status = Verification.STATUS_APPROVED
        v.verified_at = timezone.now()
        v.verified_by = None  # 邮箱自证，无审核人
        v.expires_at = v.verified_at + timedelta(days=verification_valid_days())
        v.save(update_fields=["status", "verified_at", "verified_by", "expires_at"])
    if user.email != v.identifier:
        user.email = v.identifier
        user.save(update_fields=["email"])
    return JsonResponse({"message": "邮箱认证成功。"})


@require_POST
def resend_verification_view(request):
    """重发邮箱认证邮件：POST {email}，按 email 通道 identifier 查待验账号。

    不泄密：无论邮箱是否存在 / 是否在验 / 已认证，返回同样提示（防账号探测）。
    只对「存在 pending email 通道、账号启用」的账号真正发信（发往待验 identifier）。
    不校验后缀白名单（ADR-0023 决策 4）：只重发既有待认证地址，不接收新地址。
    """
    if not get_policy().verification_enabled:
        return _verification_closed_response()
    if not ResendVerificationThrottle().allow_request(request, None):
        return JsonResponse({"error": "请求过于频繁，请稍后再试。"}, status=429)

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    email = (body.get("email") or "").strip().lower()
    if not email:
        return JsonResponse({"error": "请输入邮箱。"}, status=400)

    if not passes_turnstile(request, body.get("turnstile_token") or ""):
        return turnstile_error_response()

    v = (
        Verification.objects.select_related("user")
        .filter(
            channel=Verification.CHANNEL_EMAIL,
            status=Verification.STATUS_PENDING,
            identifier__iexact=email,
        )
        .first()
    )
    if v is not None and v.user.is_active:
        _send_verification_email(v.user)

    return JsonResponse({"message": "如果该邮箱正在认证中，认证邮件已重发。"})


@login_required
def identity_proof_file_view(request, pk):
    """身份证明鉴权下载（#31）：仅本人或持 can_review_identity 者可读。

    文件存 PRIVATE_MEDIA_ROOT 私有存储，绝不经公开 MEDIA_URL 暴露（DEBUG 下亦然——
    config/urls.py 的 static(MEDIA_URL) 只服务 MEDIA_ROOT，私有存储在其外）。
    """
    proof = get_object_or_404(IdentityProof, pk=pk)
    user = request.user
    if proof.user_id != user.pk and not user.has_perm("accounts.can_review_identity"):
        return HttpResponseForbidden("无权访问该身份证明。")

    if not proof.file.storage.exists(proof.file.name):
        raise Http404("证明文件不存在")

    content_type, _ = mimetypes.guess_type(proof.file.name)
    return FileResponse(
        proof.file.open("rb"),
        content_type=content_type or "image/jpeg",
    )


def _get_or_create_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _email_domain_blocked_response(email):
    """邮箱后缀不在白名单（ADR-0023）：固定文案 + 专属 reason + 命中的域名。

    前端据 reason 映射成类型化 ``email_domain_not_allowed`` 并用 NoticeModal 弹窗展示文案
    （文案在 accounts.email_domains 与 frontend/src/api/shared.ts 各一份，契约测试钉死一致）。
    """
    return JsonResponse(
        {
            "error": EMAIL_DOMAIN_BLOCKED_MESSAGE,
            "reason": EMAIL_DOMAIN_BLOCKED_REASON,
            "domain": email_domain(email),
        },
        status=400,
    )


def _email_taken(email, exclude_user=None):
    """邮箱是否已被他账号有效持有：User.email（已认证绑定）或他人 email 通道 identifier（含 pending）。

    绑定唯一性（ADR-0006 决策 10）：一个邮箱同一时刻只能被一个账号有效持有（已绑定或正在验）。
    """
    users = User.objects.filter(email__iexact=email)
    vs = Verification.objects.filter(channel=Verification.CHANNEL_EMAIL, identifier__iexact=email)
    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)
        vs = vs.exclude(user=exclude_user)
    return users.exists() or vs.exists()


def _user_from_uid(uid):
    """uid（urlsafe_base64）→ User；非法返回 None。"""
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        return User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return None


def _capabilities(user):
    """前端能力契约：由 has_perm 派生的语义化布尔（解耦权限代号）。"""
    return {
        "can_manage_news": user.has_perm("news.manage_news"),
        "can_manage_tasks": user.has_perm("tasks.manage_tasks"),
        "can_assign_task": user.has_perm("tasks.assign_task"),
        "can_manage_tags": user.has_perm("common.manage_tags"),
        "can_change_activity": user.has_perm("activities.manage_activity"),
        "can_view_feedback": user.has_perm("reviews.read_feedback"),
        "can_handle_reports": user.has_perm("reviews.handle_report"),
        "can_review_collections": user.has_perm("activities.review_collection"),
        "can_edit_about": user.has_perm("about.manage_aboutpage"),
        "can_manage_panoramas": user.has_perm("panorama.manage_panoramas"),
        "can_manage_exam": user.has_perm("exam_board.manage_exams"),
        "can_review_content": user.has_perm("reviews.moderate"),
        "can_review_identity": user.has_perm("accounts.can_review_identity"),
        "can_force_publish": user.has_perm("reviews.force_publish"),
        "can_manage_comment_thread": user.has_perm("messaging.manage_comment_thread"),
        "can_mute_user": user.has_perm("reviews.mute_user"),
        "can_manage_announcement": user.has_perm("messaging.manage_announcement"),
        "can_manage_announcements": user.has_perm("announcements.manage_announcements"),
        # 密码重置审批（忘记密码 → 管理员手动重置）：审核台「密码重置」桌。
        "can_review_password_reset": user.has_perm("accounts.review_password_reset"),
    }


def _role_for(user):
    """身份徽章 {label, variant}：超管 > 管理员 > 用户 > 访客（ADR-0005 决策 7 / ADR-0006）。

    与组、权限解耦——纯身份态派生；variant 供前端徽章配色。「用户 / 访客」分界读
    ``is_verified``（任一认证通道通过即用户，否则访客）。
    """
    if not user.is_authenticated:
        return {"label": "访客", "variant": "visitor"}
    if user.is_superuser:
        return {"label": "超级管理员", "variant": "superadmin"}
    if user.is_staff:
        return {"label": "管理员", "variant": "admin"}
    if is_verified(user):
        return {"label": "用户", "variant": "user"}
    return {"label": "访客", "variant": "visitor"}


def _public_role_for(viewed, viewer):
    """**对外**展示的身份徽章：超级管理员一律显示为「管理员」（ADR-0042）。

    超管的存在只在后台与本人可见——访客 / 普通成员查看他人主页时看不到
    ``superadmin`` 徽章，避免通过徽章反推出站点存在超级管理员账户。
    本人查看自己的快照仍走 :func:`_role_for`（``/auth/me/``），不受影响。
    """
    role = _role_for(viewed)
    if role["variant"] == "superadmin" and (
        viewer is None or getattr(viewer, "pk", None) != viewed.pk
    ):
        return {"label": "管理员", "variant": "admin"}
    return role


def _profile_response(user, profile):
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "permissions": _capabilities(user),
        },
        # 管理员重置后的强制改密标记（前端启动 / 登录后据此跳转改密页）。
        "must_change_password": bool(profile.must_change_password),
        # 身份徽章（ADR-0005 决策 7）：前端据此（而非单看 is_verified）决定是否提示去认证——
        # 超管 / 管理员 / 已认证用户均不提示，仅访客（未认证普通成员）提示。
        "role": _role_for(user),
        "profile": {
            "avatar": profile.avatar.url if profile.avatar else None,
            "nickname": profile.nickname,
            "birthday": profile.birthday.isoformat() if profile.birthday else None,
            "gender": profile.gender,
            "bio": profile.bio,
            # 认证态（ADR-0006）：前端据此显访客提示 / 引导去认证面板。
            "is_verified": is_verified(user),
        },
    }


@login_required
def profile_view(request):
    profile = _get_or_create_profile(request.user)
    return JsonResponse(_profile_response(request.user, profile))


@require_POST
@login_required
def profile_update_view(request):
    profile = _get_or_create_profile(request.user)

    avatar = request.FILES.get("avatar")
    if avatar:
        if avatar.size > 2 * 1024 * 1024:
            return JsonResponse({"error": "头像文件不能超过 2MB"}, status=400)
        if avatar.content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            return JsonResponse({"error": "仅支持 JPG、PNG、GIF、WebP 格式"}, status=400)
        profile.avatar = avatar

    form = ProfileForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": _form_errors(form)}, status=400)

    for field in ("nickname", "birthday", "gender", "bio"):
        setattr(profile, field, form.cleaned_data[field])

    profile.save()
    return JsonResponse(_profile_response(request.user, profile))


def _rotate_session_record(request, user):
    """改密后同步本设备登录记录到轮换后的 session key（ADR-0028）。

    ``update_session_auth_hash`` 会轮换 session key（防会话固定）：旧 key 的记录标为
    「设备重登」让出名额，新 key 重新登记为本机，否则同一台设备会占掉两个名额 /
    下一次请求被判「已下线」。
    """
    previous_key = request.session.session_key
    update_session_auth_hash(request, user)
    new_key = request.session.session_key
    if previous_key and previous_key != new_key:
        UserSession.objects.filter(session_key=previous_key).update(
            revoked_at=timezone.now(),
            revoked_reason=UserSession.REVOKE_REPLACED,
            replaced_by_session_key=new_key or "",
        )
    record_user_session(request, user, new_key or "")


@require_POST
@login_required
def force_change_password_view(request):
    """管理员重置后的首次登录强制改密（不要求原密码，因为默认密码是公开的）。

    只允许在 ``Profile.must_change_password=True`` 时调用；成功后清标记并保持当前会话。
    """
    profile = _get_or_create_profile(request.user)
    if not profile.must_change_password:
        return JsonResponse(
            {"error": "当前账号无需强制改密。", "reason": "not_required"},
            status=400,
        )

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    new_password = body.get("new_password") or ""
    new_password2 = body.get("new_password2") or ""
    errors = []
    if not new_password:
        errors.append("新密码不能为空")
    if new_password != new_password2:
        errors.append("两次输入的密码不一致")
    if new_password and new_password == DEFAULT_RESET_PASSWORD:
        errors.append("新密码不能与默认密码相同")
    if new_password:
        try:
            validate_password(new_password)
        except ValidationError as e:
            errors.extend(e.messages)
    if new_password and request.user.check_password(new_password):
        errors.append("新密码不能与原密码相同")
    if errors:
        return JsonResponse({"error": errors[0] if len(errors) == 1 else errors}, status=400)

    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    profile.must_change_password = False
    profile.save(update_fields=["must_change_password"])
    _rotate_session_record(request, request.user)
    request.session["pwd_change_required"] = False
    return JsonResponse({"message": "密码已修改，请使用新密码继续使用。"})


@require_POST
@login_required
def change_password_view(request):
    # 敏感操作：需安全验证（ADR-0026）。缺 grant → 403 step_up_required，
    # 前端跳 /#/verify?action=change_password&next=…，验证完成后回跳重试。
    if not stepup.grant_from_request(request, "change_password"):
        return stepup.stepup_required_response("change_password")

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    form = ChangePasswordForm(body)
    if not form.is_valid():
        return JsonResponse({"error": _form_errors(form)}, status=400)

    if not request.user.check_password(form.cleaned_data["old_password"]):
        return JsonResponse({"error": "原密码不正确"}, status=400)

    request.user.set_password(form.cleaned_data["new_password"])
    request.user.save()
    # 保持当前会话（否则改密后本会话立即失效）——安全验证「完成即回跳重试」流程的前提。
    # 轮换后的 session key 与本设备记录同步见 _rotate_session_record（ADR-0028）。
    _rotate_session_record(request, request.user)
    # 自行改密同样解除强制改密（管理员重置后用户若从个人中心改密，也视为已完成）。
    profile = _get_or_create_profile(request.user)
    if profile.must_change_password:
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
    request.session["pwd_change_required"] = False
    return JsonResponse({"message": "密码修改成功"})


@require_POST
@login_required
def delete_account_view(request):
    """自助注销账号（ADR-0027）：密码 + 逐字确认口令，成功后立即登出。

    软删除：账号行保留（后台可见「已注销」）、真实姓名与账号编码不删；
    邮箱 / 验证材料 / 会话等敏感信息由 ``accounts.deletion.delete_account`` 清除。
    """
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # 敏感操作：有可用安全验证方式时必须先完成 Step-up（ADR-0026）；
    # 既没认证邮箱也没设安全问题的账号退回「密码 + 逐字确认」。
    if not stepup.grant_from_request(request, "delete_account") and stepup.stepup_available(request.user):
        return stepup.stepup_required_response("delete_account")

    if (body.get("confirm") or "") != "注销账号":
        return JsonResponse(
            {"error": "请完整输入「注销账号」以确认。", "reason": "confirmation_required"},
            status=400,
        )
    password = body.get("password") or ""
    if not password:
        return JsonResponse({"error": "请输入当前密码。", "reason": "password_required"}, status=400)
    if not request.user.check_password(password):
        return JsonResponse({"error": "密码不正确。", "reason": "password_incorrect"}, status=400)

    try:
        delete_account(request.user)
    except AccountDeletionError as exc:
        return JsonResponse(
            {"error": exc.message, "reason": exc.reason}, status=exc.status,
        )

    auth_logout(request)
    return JsonResponse({"message": "账号已注销"})


@require_GET
@login_required
def users_view(request):
    """用户列表（给任务表单选人用）：DRF 分页 + 可选 ?search=（用户名/昵称模糊）。

    分页信封与 DRF 默认保持一致（count/next/previous/results，页大小 20）。
    search 为空时返回全部激活用户的第一页（任务表单搜人用，前端按需追加页）。
    """
    qs = User.objects.select_related("profile").filter(is_active=True).order_by("username", "id")
    search = (request.GET.get("search") or "").strip()
    if search:
        qs = qs.filter(Q(username__icontains=search) | Q(profile__nickname__icontains=search))

    paginator = PageNumberPagination()
    try:
        page = paginator.paginate_queryset(qs, Request(request))
    except NotFound:
        # 越界页：返回空 results，信封仍在（前端页码器不会请求越界页，防御性处理）
        return JsonResponse({"count": qs.count(), "next": None, "previous": None, "results": []})

    data = []
    for u in page:
        profile = getattr(u, "profile", None)
        data.append({
            "id": u.id, # type: ignore
            "username": u.username,
            "nickname": profile.nickname if profile else "",
            "avatar": profile.avatar.url if profile and profile.avatar else None,
        })
    return JsonResponse({
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": data,
    })


@require_GET
@login_required
def user_profile_view(request, id):
    """查看任意用户的主页资料（按请求者身份裁剪字段，委托可见性模块）。

    已注销账号（``Profile.deleted_at``）返回**墓碑响应**（``deleted: true``）：只给 id /
    注册时间，不泄露用户名 / 昵称 / 资料 / 权限；前端渲染「该用户已注销」。
    其它已停用账号仍按「用户不存在」处理（不暴露停用状态）。
    """
    viewed = User.objects.select_related("profile").filter(pk=id).first()
    if viewed is None:
        return JsonResponse({"error": "用户不存在"}, status=404)

    profile = _get_or_create_profile(viewed)
    if profile.deleted_at is not None:
        return JsonResponse({
            "deleted": True,
            "user": {
                "id": viewed.id,
                "username": "",
                "date_joined": viewed.date_joined.isoformat(),
            },
            "profile": {"avatar": None, "nickname": "", "bio": ""},
            "role": {"label": "已注销", "variant": "visitor"},
            "viewer": {
                "is_owner": False,
                "is_admin": profile_view_for(request.user, viewed).is_admin,
            },
        })

    if not viewed.is_active:
        return JsonResponse({"error": "用户不存在"}, status=404)

    visibility = profile_view_for(request.user, viewed)

    data = {
        "user": {
            "id": viewed.id,
            "username": viewed.username,
            "date_joined": viewed.date_joined.isoformat(),
        },
        "profile": {
            "avatar": profile.avatar.url if profile.avatar else None,
            "nickname": profile.nickname,
            "bio": profile.bio,
        },
        "role": _public_role_for(viewed, request.user),
        "viewer": {"is_owner": visibility.is_owner, "is_admin": visibility.is_admin},
    }

    if visibility.can_see_private:
        data["user"]["email"] = viewed.email
        data["profile"]["birthday"] = profile.birthday.isoformat() if profile.birthday else None
        data["profile"]["gender"] = profile.gender

    if visibility.can_see_sensitive:
        data["permissions"] = _capabilities(viewed)
        data["groups"] = list(viewed.groups.values_list("name", flat=True))

    return JsonResponse(data)


@require_GET
@login_required
def user_content_view(request, id):
    """某用户的 tab 内容（按身份裁剪可见性，委托可见性模块）。

    分页（CONTENT_LIMIT/页）：前端内容面板「加载更多」逐页向下翻。
    """
    viewed = User.objects.filter(pk=id, is_active=True).first()
    if viewed is None:
        return JsonResponse({"error": "用户不存在"}, status=404)

    type_ = request.GET.get("type")
    if type_ not in ("news", "feedback", "tasks", "activities", "tutorials"):
        return JsonResponse({"error": "无效的 type"}, status=400)

    visibility = content_visibility(request.user, viewed, type_)
    if visibility.denied:
        return JsonResponse({"error": "无权查看他人任务"}, status=403)

    from reviews.visibility import status_of
    if type_ == "news":
        from news.models import News
        qs = News.objects.filter(author=viewed).filter(visibility.extra_q).select_related("review").order_by("-created_at", "-id")
    elif type_ == "feedback":
        from reviews.models import Feedback
        qs = Feedback.objects.filter(creator=viewed).filter(visibility.extra_q).order_by("-created_at", "-id")
    elif type_ == "activities":
        from activities.models import Activity
        qs = Activity.objects.filter(creator=viewed).filter(visibility.extra_q).select_related("publication_review").order_by("-created_at", "-id")
    elif type_ == "tutorials":
        from tutorials.models import Tutorial
        qs = Tutorial.objects.filter(uploader=viewed).filter(visibility.extra_q).select_related("review").order_by("-created_at", "-id")
    else:  # tasks（visibility.denied 已保证仅本人到此）
        from tasks.models import Task
        qs = Task.objects.filter(assignee=viewed).filter(visibility.extra_q).order_by("-created_at", "-id")

    paginator = PageNumberPagination()
    paginator.page_size = CONTENT_LIMIT
    try:
        page = paginator.paginate_queryset(qs, Request(request))
    except NotFound:
        return JsonResponse({"count": qs.count(), "next": None, "previous": None, "results": []})

    if type_ == "news":
        results = [{
            "id": n.id,
            "title": n.title,
            "cover_image": n.cover_image.url if n.cover_image else None,
            "is_published": n.is_published,
            "review_status": status_of(n),
            "published_at": (n.published_at or n.created_at).isoformat(),
        } for n in page]
    elif type_ == "feedback":
        results = [{
            "id": p.id,
            "title": p.title,
            "category": p.category,
            "status": p.status,
            "created_at": p.created_at.isoformat(),
        } for p in page]
    elif type_ == "activities":
        results = [{
            "id": a.id,
            "title": a.title,
            "type": a.type,
            "status": a.status,
            "review_status": status_of(a),
            "created_at": a.created_at.isoformat(),
        } for a in page]
    elif type_ == "tutorials":
        results = [{
            "id": t.id,
            "title": t.title,
            "review_status": status_of(t),
            "created_at": t.created_at.isoformat(),
        } for t in page]
    else:
        results = [{
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "created_at": t.created_at.isoformat(),
        } for t in page]

    return JsonResponse({
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": results,
    })
