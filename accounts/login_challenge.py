"""陌生设备登录：二次验证挑战（P3）。

流程（用户 2026-10-24 定的原则）：
- 设备初始一律陌生；密码正确后若设备未经二次验证 → 不建 session，返回 202 + challenge；
- 通过 TOTP / 邮箱码 / 安全问题 / 恢复代码任一 → 建 session，设备 trusted_at=now；
- 用户没有任何二次验证方式 → 本次豁免放行（`must_bind_2fa=true`），设备保持陌生。
"""
from __future__ import annotations

import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import stepup, totp
from .devices import get_client_ip, record_login_event
from .models import AccountDevice, LoginChallenge, Profile, RecoveryCode, SecurityQuestion, TotpDevice

CHALLENGE_TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


def available_factors(user) -> list[str]:
    """该账号当前真正可用的二次验证方式（按强度排序）。"""
    methods: list[str] = []
    if TotpDevice.objects.filter(user=user, confirmed_at__isnull=False).exists():
        methods.append("totp")
    if stepup.email_available(user):
        methods.append("email_code")
    if SecurityQuestion.objects.filter(user=user).exists():
        methods.append("question")
    if RecoveryCode.objects.filter(user=user, used_at__isnull=True).exists():
        methods.append("recovery")
    return methods


def create_challenge(user, device_id: str, remember: bool) -> LoginChallenge:
    return LoginChallenge.objects.create(
        user=user,
        token=secrets.token_urlsafe(32)[:64],
        device_id=device_id,
        methods=available_factors(user),
        remember=remember,
        expires_at=timezone.now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
    )


def challenge_payload(challenge: LoginChallenge) -> dict:
    questions = [
        {"id": q.id, "text": q.question_text}
        for q in SecurityQuestion.objects.filter(user=challenge.user)
    ]
    return {
        "challenge": challenge.token,
        "methods": challenge.methods,
        "questions": questions,
        "reason": "new_device",
        "expires_in": CHALLENGE_TTL_SECONDS,
    }


def _get_challenge(token: str) -> LoginChallenge | None:
    if not token:
        return None
    return LoginChallenge.objects.filter(
        token=token, consumed_at__isnull=True, expires_at__gt=timezone.now()
    ).first()


@require_POST
def challenge_send_view(request):
    """给挑战发一封邮箱验证码（仅当 method 含 email_code）。"""
    body = _body(request)
    challenge = _get_challenge(str(body.get("token") or ""))
    if challenge is None:
        return JsonResponse({"error": "验证已过期，请重新登录。"}, status=410)
    if "email_code" not in challenge.methods:
        return JsonResponse({"error": "该账号未绑定可用邮箱。"}, status=400)

    remaining = stepup.email_cooldown_remaining(challenge.user)
    if remaining > 0:
        return JsonResponse(
            {"error": f"发送太频繁，请 {remaining} 秒后再试。", "retry_after": remaining}, status=429
        )
    try:
        stepup.send_email_code(challenge.user)
    except stepup.StepUpError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "邮件发送失败，请稍后重试。"}, status=500)
    return JsonResponse({"message": "验证码已发送，请查收邮件。"})


@require_POST
def challenge_verify_view(request):
    """校验二次验证 → 建 session 并把设备标记为已知。"""
    body = _body(request)
    challenge = _get_challenge(str(body.get("token") or ""))
    if challenge is None:
        return JsonResponse({"error": "验证已过期，请重新登录。"}, status=410)

    method = str(body.get("method") or "")
    if method not in challenge.methods:
        return JsonResponse({"error": "该验证方式不可用。"}, status=400)

    user = challenge.user
    verified = False
    try:
        if method == "totp":
            code = str(body.get("code") or "")
            for device in TotpDevice.objects.filter(user=user, confirmed_at__isnull=False):
                step = totp.verify(totp.decrypt_secret(device.secret_enc), code, device.last_used_step)
                if step is not None:
                    device.last_used_step = step
                    device.save(update_fields=["last_used_step"])
                    verified = True
                    break
        elif method == "email_code":
            stepup.verify_email_code(user, str(body.get("code") or ""))
            verified = True
        elif method == "question":
            stepup.check_security_answer(user, int(body.get("question_id") or 0), str(body.get("answer") or ""))
            verified = True
        elif method == "recovery":
            verified = _consume_recovery_code(user, str(body.get("code") or ""))
    except (stepup.StepUpError, ValueError, TypeError):
        verified = False

    if not verified:
        challenge.attempts += 1
        if challenge.attempts >= MAX_ATTEMPTS:
            challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["attempts", "consumed_at"])
        remaining = max(0, MAX_ATTEMPTS - challenge.attempts)
        return JsonResponse(
            {"error": "验证未通过。" if remaining else "失败次数过多，请重新登录。", "remaining": remaining},
            status=400,
        )

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])

    device = AccountDevice.objects.filter(user=user, device_id=challenge.device_id).first()
    if device is not None and device.revoked_at is not None:
        device.revoked_at = None
    if device is not None:
        device.trusted_at = timezone.now()
        device.save(update_fields=["trusted_at", "revoked_at"])

    login(request, user)
    request.session.set_expiry(settings.REMEMBER_LOGIN_SECONDS if challenge.remember else 0)
    must_change = Profile.objects.filter(user=user, must_change_password=True).exists()
    request.session["pwd_change_required"] = must_change
    record_login_event(
        request,
        user=user,
        device=device,
        status="success",
        method="password",
        second_factor=method,
        is_new_device=True,
        session_key=request.session.session_key or "",
    )
    return JsonResponse(
        {
            "user": {"id": user.id, "username": user.username, "email": user.email},
            "must_change_password": must_change,
            "device_trusted": True,
        }
    )


def _consume_recovery_code(user, raw: str) -> bool:
    hashed = totp.hash_recovery_code(raw)
    row = RecoveryCode.objects.filter(user=user, code_hash=hashed, used_at__isnull=True).first()
    if row is None:
        return False
    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])
    return True


@require_GET
@login_required
def challenge_status_view(request):
    """当前账号的二次验证可用性（前端「绑定提醒」用）。"""
    return JsonResponse({"methods": available_factors(request.user)})
