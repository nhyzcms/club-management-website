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
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth import login, logout as auth_logout
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

from .authcode import AuthCodeError, redeem_authcode
from .email_domains import (
    EMAIL_DOMAIN_BLOCKED_MESSAGE,
    EMAIL_DOMAIN_BLOCKED_REASON,
    email_domain,
    is_allowed_email_domain,
)
from .forms import LoginForm, PasswordResetForm, PasswordResetConfirmForm, ProfileForm, ChangePasswordForm
from .models import Profile, IdentityProof, UserSession, Verification, is_verified, verification_valid_days
from .tokens import email_verification_token
from .throttles import (
    AuthCodeRedeemThrottle,
    RegisterThrottle,
    ResendVerificationThrottle,
    login_blocked_response,
)
from .turnstile import passes_turnstile, turnstile_error_response
from .utils import SESSION_HISTORY_LIMIT
from .validity import enforce_account_validity
from .visibility import content_visibility, profile_view_for

logger = logging.getLogger(__name__)

LOGIN_PROTECTION_SECONDS = 600  # 登录保护窗口：登录后 10 分钟内他方新会话登录被拒
CONTENT_LIMIT = 15  # 个人中心每个内容 tab 返回的最近条数

_EXPIRED_UNVERIFIED_MESSAGE = "本账户超过 60 日未认证，已被系统停用。请联系社长或服务器管理员处理。"


def _verification_closed_response():
    return JsonResponse(
        {"error": "验证通道已关闭", "reason": "verification_closed"},
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
    """发邮箱验证邮件到 **待验邮箱**（email 通道 identifier，非 User.email）。

    链接 = FRONTEND_URL + #/verify-email?uid=&token=。令牌绑 identifier + 通道 status
    （见 accounts.tokens）：改邮箱或验证通过后旧令牌失效。发信失败仅记日志、不抛——
    账号已建，用户可走「重发」补发，不因 SMTP 抖动回滚。无待验邮箱则不发。
    """
    v = user.verifications.filter(channel=Verification.CHANNEL_EMAIL).first()
    if v is None or not v.identifier:
        return  # 无待验邮箱：无可发（注册未留邮箱等情况）
    recipient = v.identifier
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    link = f"{settings.FRONTEND_URL}/#/verify-email?uid={uid}&token={token}"
    try:
        send_mail(
            subject="邮箱验证 - 南汇一中传媒社",
            message=(
                "你好！请点击下方链接完成邮箱验证：\n\n"
                f"{link}\n\n"
                "如果你没有注册过本社团账号，请忽略此邮件。"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=True,
        )
    except Exception:
        logger.exception("发送邮箱验证邮件失败: user_pk=%s", user.pk)


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

    # 用 check_password 而非 authenticate：密码正确后再区分「停用 / 未验证」，
    # 错误密码统一回 401，不泄露账号存在性与状态（防枚举）。
    candidate = User.objects.filter(username=username).first() if username else None
    if candidate is None or not candidate.check_password(form.cleaned_data["password"]):
        user_login_failed.send(
            sender=User,
            request=request,
            credentials={"username": throttle_ident},
        )
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
        if Profile.objects.filter(user=candidate, expiry_disabled_at__isnull=False).exists():
            return JsonResponse(
                {"error": _EXPIRED_UNVERIFIED_MESSAGE, "reason": "account_expired_unverified"},
                status=403,
            )
        return JsonResponse(
            {"error": "账号已停用，请联系信息组。", "reason": "account_disabled"},
            status=403,
        )
    # 登录与验证解耦（ADR-0006 决策 6）：未验证账号可登录为访客，仅 is_active 拒停用。
    # 写操作门禁由 IsVerified 单独管（未验证能登、能读，不能写）。

    # 10 分钟登录保护：该账号已有当前会话且登录未满窗口、且非同一会话再认证 → 拒绝
    existing = UserSession.objects.filter(user=candidate, is_current=True).first()
    if existing:
        age = timezone.now() - existing.created_at
        same_session = existing.session_key == request.session.session_key
        if not same_session and age < timedelta(seconds=LOGIN_PROTECTION_SECONDS):
            retry_after = max(0, int(LOGIN_PROTECTION_SECONDS - age.total_seconds()))
            return JsonResponse(
                {
                    "error": "Login protection active",
                    "reason": "login_protection",
                    "retry_after": retry_after,
                },
                status=409,
            )

    login(request, candidate)
    return JsonResponse({"user": {"id": candidate.id, "username": candidate.username, "email": candidate.email}}) # type: ignore



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
    user = request.user
    auth_logout(request)
    UserSession.objects.filter(user=user, is_current=True).update(is_current=False)
    return JsonResponse({"message": "Logged out"})


@require_GET
@login_required
def verification_status_view(request):
    """账号验证状态（#36）：总 is_verified + 各通道当前状态，数据驱动面板铺卡。

    每个已定义通道一卡，按 CHANNELS 序。无 Verification 行的通道 status="none"（前端映射
    「未绑定 / 未提交」；后台委任 none 不铺卡）。通道对象键集与前端 VerificationPanel 契约
    （见契约测试）。``is_verified`` 已含有效期判定（ADR-0041），键集契约保持不变。
    """
    user = request.user
    rows = {v.channel: v for v in user.verifications.all()}
    channels = []
    for channel, _label in Verification.CHANNELS:
        v = rows.get(channel)
        channels.append({
            "channel": channel,
            "status": v.status if v else "none",
            "identifier": v.identifier if v else "",
            "verified_at": v.verified_at.isoformat() if v and v.verified_at else None,
        })
    return JsonResponse({"is_verified": is_verified(user), "channels": channels})


@require_POST
@login_required
def verification_email_bind_view(request):
    """邮箱通道绑定 / 重发 / 换邮（面板动作，#37 / ADR-0006）。

    统一为「email 通道置 pending + identifier=待验地址 + 发信」，``User.email`` 不动（待验邮箱
    不住此）——验证通过才晋升（见 verify_email_view）。故：
      - 首次绑定 / 重发同邮箱 → 建或刷新 pending 行并发信；
      - 换邮箱（含已验证旧邮箱）→ 回 pending(identifier=新)，旧 User.email 在新验证前仍有效；
      - 已验证且未过期同邮箱再绑 → no-op（不降级）；过期则回落重新验证。
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
    # 已验证且未过期同邮箱再绑 → no-op（不降级为 pending、不重发）
    if (
        existing is not None
        and existing.status == Verification.STATUS_APPROVED
        and existing.identifier == email
        and (existing.expires_at is None or existing.expires_at > timezone.now())
    ):
        return JsonResponse({"message": "该邮箱已验证。"})

    # 后缀白名单（ADR-0023）：只拦「新地址」；既有同址（重发 / 复绑，含白名单上线前留下的
    # 非白名单地址）放行——不回溯旧数据，否则这批人会被卡在验证中途。
    same_identifier = existing is not None and existing.identifier == email
    if not same_identifier and not is_allowed_email_domain(email):
        return _email_domain_blocked_response(email)

    # 唯一性：不可绑他账号有效持有的邮箱（已验证 User.email 或他人 pending identifier）
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
    return JsonResponse({"message": "验证邮件已发送，请查收。"})


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
        return JsonResponse({"error": "账号已完成验证，无需使用认证码。"}, status=400)

    try:
        redeem_authcode(request.user, code)
    except AuthCodeError as exc:
        throttle.allow_request(request, None)  # 只计失败：成功不占额度
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({"message": "认证码验证通过，账号已完成验证。"})


@login_required
def me_view(request):
    profile = _get_or_create_profile(request.user)
    return JsonResponse(_profile_response(request.user, profile))


@require_GET
@login_required
def sessions_view(request):
    """本人最近登录记录（设备/IP/时间，当前会话高亮），按时间倒序裁剪到历史上限。

    数据本身按用户裁剪到 SESSION_HISTORY_LIMIT 条，分页按同上限做单页，
    返回完整信封（count/next/previous/results）供前端统一消费。
    """
    qs = UserSession.objects.filter(user=request.user).order_by("-created_at", "-id")
    paginator = PageNumberPagination()
    paginator.page_size = SESSION_HISTORY_LIMIT
    page = paginator.paginate_queryset(qs, Request(request))  # 单页（存储层已裁剪）
    return JsonResponse({
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": [
            {
                "id": r.id, # type: ignore
                "device_name": r.device_name,
                "device_type": r.device_type,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat(),
                "is_current": r.is_current,
            }
            for r in page
        ],
    })


@require_POST
def password_reset_view(request):
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

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
def register_view(request):
    """注册（ADR-0006，2026-09 修订）：建登录身份（用户名 + 密码 + Turnstile）+ 真实姓名 / 身份（必填）。

    注册↔验证分离：邮箱 / 身份证明仍挪在验证面板；但 real_name / identity 为注册必填，
    写入 Profile（identity 须合法枚举）。新号无 Verification 行 ⇒ 未验证（访客）。
    若提供邮箱：须过**后缀白名单**（ADR-0023），再建 email 通道 pending（identifier=待验地址）
    并发验证信，``User.email`` 保持空（待验邮箱不住 User.email）——验证通过才晋升
    （见 verify_email_view）。
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

    # 邮箱可选；填了须格式合法 + 唯一（User.email 或他人 pending identifier 均判重）。
    if email:
        try:
            EmailValidator()(email)
        except ValidationError:
            errors.append("邮箱格式不正确")
        if _email_taken(email):
            errors.append("该邮箱已被占用")

    # 用户名唯一（大小写不敏感）。
    if username and User.objects.filter(username__iexact=username).exists():
        errors.append("该用户名已被占用")

    if errors:
        return JsonResponse({"error": errors[0] if len(errors) == 1 else errors}, status=400)

    # Turnstile：两项密钥都空则关闭并放行；启用时校验失败拒注册。
    if not passes_turnstile(request, turnstile_token):
        return turnstile_error_response()

    started_email = False
    try:
        with transaction.atomic():
            # User.email 只装已验证邮箱：注册阶段留空；邮箱验证通过才晋升写入。
            user = User.objects.create_user(
                username=username, email="", password=password, is_active=True
            )
            Profile.objects.create(user=user, real_name=real_name, identity=identity)
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

    return JsonResponse(
        {
            "message": "注册成功。" + ("请查收邮件完成邮箱验证。" if started_email else ""),
            "user": {"id": user.id, "username": user.username},
        },
        status=201,
    )


@require_GET
def verify_email_view(request):
    """邮箱验证：GET /auth/verify-email/?uid=&token= → email 通道 approved + 晋升 User.email。

    令牌绑 identifier + 通道 status（见 tokens）：改待验邮箱或验证通过后旧令牌失效。
    验证通过：identifier 晋升写入 User.email（绑定邮箱生效，可用邮箱登录 / 重置密码）。
    ADR-0041：通过时设 expires_at = 通过日 + 认证有效期。
    不校验后缀白名单（ADR-0023 决策 4）：令牌已限定为既有 pending 地址，落地即完成该地址的验证。
    """
    if not get_policy().verification_enabled:
        return _verification_closed_response()
    user = _user_from_uid(request.GET.get("uid", ""))
    token = request.GET.get("token", "")
    if user is None or not email_verification_token.check_token(user, token):
        return JsonResponse({"error": "验证链接无效或已过期。", "reason": "invalid"}, status=400)

    v = user.verifications.filter(channel=Verification.CHANNEL_EMAIL).first()
    if v is None or not v.identifier:
        return JsonResponse({"error": "验证链接无效或已过期。", "reason": "invalid"}, status=400)

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
    return JsonResponse({"message": "邮箱验证成功。"})


@require_POST
def resend_verification_view(request):
    """重发邮箱验证邮件：POST {email}，按 email 通道 identifier 查待验账号。

    不泄密：无论邮箱是否存在 / 是否在验 / 已验证，返回同样提示（防账号探测）。
    只对「存在 pending email 通道、账号启用」的账号真正发信（发往待验 identifier）。
    不校验后缀白名单（ADR-0023 决策 4）：只重发既有待验地址，不接收新地址。
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

    return JsonResponse({"message": "如果该邮箱正在验证中，验证邮件已重发。"})


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
    """邮箱是否已被他账号有效持有：User.email（已验证绑定）或他人 email 通道 identifier（含 pending）。

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
        "can_manage_tags": user.has_perm("tasks.manage_tags"),
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
    }


def _role_for(user):
    """身份徽章 {label, variant}：超管 > 管理员 > 用户 > 访客（ADR-0005 决策 7 / ADR-0006）。

    与组、权限解耦——纯身份态派生；variant 供前端徽章配色。「用户 / 访客」分界读
    ``is_verified``（任一验证通道通过即用户，否则访客）。
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


def _profile_response(user, profile):
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "permissions": _capabilities(user),
        },
        # 身份徽章（ADR-0005 决策 7）：前端据此（而非单看 is_verified）决定是否提示去验证——
        # 超管 / 管理员 / 已验证用户均不提示，仅访客（未验证普通成员）提示。
        "role": _role_for(user),
        "profile": {
            "avatar": profile.avatar.url if profile.avatar else None,
            "nickname": profile.nickname,
            "birthday": profile.birthday.isoformat() if profile.birthday else None,
            "gender": profile.gender,
            "bio": profile.bio,
            # 验证态（ADR-0006）：前端据此显访客提示 / 引导去验证面板。
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


@require_POST
@login_required
def change_password_view(request):
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
    return JsonResponse({"message": "密码修改成功"})


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
    """查看任意用户的主页资料（按请求者身份裁剪字段，委托可见性模块）。"""
    viewed = User.objects.filter(pk=id, is_active=True).first()
    if viewed is None:
        return JsonResponse({"error": "用户不存在"}, status=404)

    profile = _get_or_create_profile(viewed)
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
        "role": _role_for(viewed),
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
