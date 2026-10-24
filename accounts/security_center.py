"""账号安全中心 API：总览、设备、登录记录、滚动密钥、恢复代码。

页面：`/#/security`（设计稿 2026-10-24）。信任原则：设备只有完成一次二次验证才算已知，
本模块负责展示与「撤销设备 / 解绑密钥」这类需要 stepup 的敏感操作。
"""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request

from . import stepup, totp
from .models import (
    AccountDevice,
    LoginEvent,
    Profile,
    RecoveryCode,
    SecurityQuestion,
    TotpDevice,
    UserSession,
)

MAX_TOTP = totp.MAX_TOTP_DEVICES


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


def _mask_email(address: str) -> str:
    address = (address or "").strip()
    if "@" not in address:
        return ""
    name, domain = address.split("@", 1)
    if len(name) <= 2:
        masked = name[:1] + "*"
    else:
        masked = name[:1] + "*" * min(4, len(name) - 1)
    return f"{masked}@{domain}"


def _mask_ip(ip: str | None) -> str:
    if not ip:
        return ""
    if ":" in ip:
        return ip.split(":")[0] + ":****"
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.*.*"
    return ip


def _device_payload(device: AccountDevice, current_ids: set[int]) -> dict:
    return {
        "id": device.id,
        "label": device.label or f"设备 #{device.device_id[-4:]}",
        "browser": device.browser,
        "platform": device.platform,
        "brand": device.brand,
        "model": device.model,
        "city": device.last_city,
        "country": device.last_country,
        "last_seen": device.last_seen.isoformat(),
        "first_seen": device.first_seen.isoformat(),
        "trusted": device.is_trusted,
        "is_current": device.device_id in current_ids,
    }


@require_GET
@login_required
def security_overview_view(request):
    """各登录方式的状态汇总，驱动安全中心列表。"""
    user = request.user
    questions = SecurityQuestion.objects.filter(user=user).count()
    confirmed_totp = TotpDevice.objects.filter(user=user, confirmed_at__isnull=False).count()
    pending_totp = TotpDevice.objects.filter(user=user, confirmed_at__isnull=True).count()
    remaining_codes = RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
    devices = AccountDevice.objects.filter(user=user, revoked_at__isnull=True)
    session_keys = set(
        UserSession.objects.filter(user=user, revoked_at__isnull=True).values_list("device_id", flat=True)
    )

    return JsonResponse(
        {
            "password": {"enabled": user.has_usable_password()},
            "email": {
                "bound": bool((user.email or "").strip()),
                "verified": stepup.email_available(user),
                "address": _mask_email(user.email),
            },
            "questions": {"count": questions},
            "passkeys": {"count": 0, "max": 5},  # P4 接入 WebAuthn 后填真实数量
            "totp": {"count": confirmed_totp, "pending": pending_totp, "max": MAX_TOTP},
            "recovery": {"remaining": remaining_codes, "total": totp.RECOVERY_CODE_COUNT},
            "devices": {
                "count": devices.count(),
                "trusted": devices.filter(trusted_at__isnull=False).count(),
                "current": sum(1 for d in devices if d.id in session_keys),
            },
            "stepup": {
                "available": stepup.stepup_available(user),
                "email": stepup.email_available(user),
                "questions": questions > 0,
                "totp": confirmed_totp > 0,
            },
            "profile": {"must_change_password": bool(getattr(Profile.objects.filter(user=user).first(), "must_change_password", False))},
        }
    )


@require_GET
@login_required
def devices_view(request):
    """本人未撤销的设备；current 标记当前会话所在设备。"""
    current_ids = {
        device_id
        for device_id in UserSession.objects.filter(
            user=request.user, revoked_at__isnull=True
        ).values_list("device_id", flat=True)
        if device_id
    }
    devices = AccountDevice.objects.filter(user=request.user, revoked_at__isnull=True).order_by("-last_seen")
    return JsonResponse({"results": [_device_payload(d, current_ids) for d in devices]})


@require_http_methods(["DELETE"])
@login_required
def device_revoke_view(request, pk):
    """撤销设备：置 revoked_at 并吊销该设备上所有会话（需要 stepup）。"""
    if not stepup.grant_from_request(request, "manage_devices"):
        return stepup.stepup_required_response("manage_devices")

    device = get_object_or_404(AccountDevice, pk=pk, user=request.user)
    if device.revoked_at is None:
        device.revoked_at = timezone.now()
        device.save(update_fields=["revoked_at"])

    keys = list(
        UserSession.objects.filter(user=request.user, device_id=device.device_id).values_list("session_key", flat=True)
    )
    if keys:
        Session.objects.filter(session_key__in=keys).delete()
        UserSession.objects.filter(session_key__in=keys).update(
            revoked_at=timezone.now(),
            revoked_reason=UserSession.REVOKE_MANUAL,
        )
    return JsonResponse({"message": "已退出该设备"})


@require_GET
@login_required
def login_events_view(request):
    """本人登录流水（分页 20/页）；IP 默认脱敏。"""
    qs = LoginEvent.objects.filter(user=request.user).select_related("device").order_by("-created_at", "-id")
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(qs, Request(request))
    results = [
        {
            "id": event.id,
            "created_at": event.created_at.isoformat(),
            "device_label": (event.device.label if event.device else "") or "未知设备",
            "city": event.city,
            "region": event.region,
            "country": event.country,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "method": event.method,
            "status": event.status,
            "second_factor": event.second_factor,
            "is_new_device": event.is_new_device,
            "ip": _mask_ip(event.ip),
        }
        for event in page
    ]
    return JsonResponse(
        {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": results,
        }
    )


@require_GET
@login_required
def totp_list_view(request):
    rows = TotpDevice.objects.filter(user=request.user, confirmed_at__isnull=False)
    return JsonResponse(
        {
            "max": MAX_TOTP,
            "results": [
                {
                    "id": row.id,
                    "label": row.label or f"验证器 #{row.id}",
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
        }
    )


@require_POST
@login_required
def totp_setup_view(request):
    """新建一条未确认的 TOTP：返回 secret、otpauth URI 与二维码（data URI）。"""
    confirmed = TotpDevice.objects.filter(user=request.user, confirmed_at__isnull=False).count()
    pending = TotpDevice.objects.filter(user=request.user, confirmed_at__isnull=True).count()
    if confirmed >= MAX_TOTP:
        return JsonResponse({"error": f"最多绑定 {MAX_TOTP} 个滚动密钥。"}, status=400)
    if pending >= 3:
        # 防止反复 setup 堆垃圾记录
        TotpDevice.objects.filter(user=request.user, confirmed_at__isnull=True).delete()

    body = _body(request)
    label = (body.get("label") or "").strip()[:64]
    secret = totp.generate_secret()
    device = TotpDevice.objects.create(
        user=request.user, label=label, secret_enc=totp.encrypt_secret(secret)
    )
    uri = totp.provisioning_uri(secret, f"{request.user.username}-{device.id}")

    import segno

    qr = segno.make(uri).png_data_uri(scale=6, border=2)
    return JsonResponse(
        {"id": device.id, "secret": secret, "otpauth": uri, "qr": qr, "label": label}
    )


@require_POST
@login_required
def totp_confirm_view(request):
    """用 6 位码确认一条 TOTP；首次确认时顺带生成一组恢复代码。"""
    body = _body(request)
    device = get_object_or_404(
        TotpDevice,
        pk=body.get("id"),
        user=request.user,
        confirmed_at__isnull=True,
    )
    secret = totp.decrypt_secret(device.secret_enc)
    step = totp.verify(secret, str(body.get("code") or ""), device.last_used_step)
    if step is None:
        return JsonResponse({"error": "验证码不正确，请确认设备时间后重试。"}, status=400)

    device.confirmed_at = timezone.now()
    device.last_used_step = step
    device.save(update_fields=["confirmed_at", "last_used_step"])

    codes = None
    if not RecoveryCode.objects.filter(user=request.user, used_at__isnull=True).exists():
        codes = _issue_recovery_codes(request.user)
    return JsonResponse({"message": "滚动密钥已启用。", "recovery_codes": codes})


@require_http_methods(["DELETE"])
@login_required
def totp_delete_view(request, pk):
    """解绑一条 TOTP（需要 stepup，防止会话被劫持后摘掉二次验证）。"""
    if not stepup.grant_from_request(request, "manage_totp"):
        return stepup.stepup_required_response("manage_totp")
    device = get_object_or_404(TotpDevice, pk=pk, user=request.user)
    device.delete()
    remaining = TotpDevice.objects.filter(user=request.user, confirmed_at__isnull=False).count()
    return JsonResponse({"message": "已解绑。", "remaining": remaining})


@require_POST
@login_required
def recovery_codes_view(request):
    """重新生成恢复代码（作废旧码）；明文只返回这一次。"""
    if not stepup.grant_from_request(request, "manage_totp"):
        return stepup.stepup_required_response("manage_totp")
    codes = _issue_recovery_codes(request.user)
    return JsonResponse({"codes": codes, "count": len(codes)})


def _issue_recovery_codes(user) -> list[str]:
    codes = totp.generate_recovery_codes()
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(user=user, code_hash=totp.hash_recovery_code(code)) for code in codes]
    )
    return codes
