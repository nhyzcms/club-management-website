"""验证因子注册表（2026-10-25，替代两套硬编码 if/elif）。

背景：安全验证（stepup，敏感操作）与陌生设备挑战（login_challenge）原本各写一套
分支，能力还不一致——挑战支持 TOTP / 恢复代码，stepup 只支持邮箱码 / 安全问题，
导致「手机丢了想解绑 TOTP」时无路可走。

现在两者共用本注册表：

    新增一种验证方式 = 在本文件写一个 ``Factor`` + ``register(...)``
    视图 / 接口不需要改；前端从 ``GET /auth/stepup/`` 的 ``factors`` 列表
    自动拿到选项（新方式只需要补一个输入区组件）。

``excluded_scopes`` 声明「哪些 scope 不允许用本因子」：例如不能用 TOTP 自己
解绑 TOTP——丢手机时它救不了你，反而给拿到设备且知道密码的人解绑你其余设备的入口。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.utils import timezone

from . import stepup, totp
from .models import RecoveryCode, SecurityQuestion, TotpDevice


class FactorError(Exception):
    """验证失败；错误文案直接展示给用户。"""


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    # (user) -> 该用户当前是否具备此因子
    available: Callable[[object], bool]
    # (user, payload) -> None；失败抛 FactorError 或 stepup.StepUpError
    verify: Callable[[object, dict], None]
    # 该 scope 下禁止使用本因子
    excluded_scopes: frozenset = frozenset()
    # 需要先「发送验证码」的因子（前端据此显示发送按钮）
    sends_code: bool = False
    # 输入提示，前端可用于 placeholder（无则用默认）
    hint: str = ""


FACTORS: dict[str, Factor] = {}

# 兼容旧记录：设备挑战早期把邮箱因子叫 email_code
ALIASES = {"email_code": "email"}


def register(factor: Factor) -> Factor:
    FACTORS[factor.key] = factor
    return factor


def normalize(key: str) -> str:
    key = (key or "").strip()
    return ALIASES.get(key, key)


def get(key: str) -> Factor | None:
    return FACTORS.get(normalize(key))


def for_user(user, scope: str) -> list[Factor]:
    """该用户在指定 scope 下可用的因子（注册顺序即为展示顺序）。"""
    out = []
    for factor in FACTORS.values():
        if scope in factor.excluded_scopes:
            continue
        if factor.available(user):
            out.append(factor)
    return out


def verify(user, key: str, payload: dict) -> None:
    """按 key 执行验证；未知 / 不可用 / 校验失败都抛异常。"""
    factor = get(key)
    if factor is None:
        raise FactorError("未知的验证方式。")
    factor.verify(user, payload or {})


# ---- 因子实现 --------------------------------------------------------------

def _totp_available(user) -> bool:
    return TotpDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


def _verify_totp(user, payload: dict) -> None:
    code = str(payload.get("code") or "").strip()
    for device in TotpDevice.objects.filter(user=user, confirmed_at__isnull=False):
        step = totp.verify(totp.decrypt_secret(device.secret_enc), code, device.last_used_step)
        if step is not None:
            device.last_used_step = step
            device.save(update_fields=["last_used_step"])
            return
    raise FactorError("验证码不正确，请确认设备时间后重试。")


def _email_available(user) -> bool:
    return stepup.email_available(user)


def _verify_email(user, payload: dict) -> None:
    stepup.verify_email_code(user, str(payload.get("code") or ""))


def _question_available(user) -> bool:
    return SecurityQuestion.objects.filter(user=user).exists()


def _verify_question(user, payload: dict) -> None:
    try:
        question_id = int(payload.get("question_id") or 0)
    except (TypeError, ValueError):
        raise FactorError("题目不存在。")
    stepup.check_security_answer(user, question_id, str(payload.get("answer") or ""))


def _recovery_available(user) -> bool:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).exists()


def _verify_recovery(user, payload: dict) -> None:
    hashed = totp.hash_recovery_code(str(payload.get("code") or ""))
    row = RecoveryCode.objects.filter(
        user=user, code_hash=hashed, used_at__isnull=True
    ).first()
    if row is None:
        raise FactorError("恢复代码无效或已使用。")
    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])


# 注册顺序 = 展示顺序 = 强度优先（动态口令 > 邮箱 > 安全问题 > 恢复代码）
register(
    Factor(
        "totp",
        "动态口令",
        _totp_available,
        _verify_totp,
        # 不能用 TOTP 自己解绑 TOTP（丢手机时无解，且扩大设备失窃的影响面）
        excluded_scopes=frozenset({"manage_totp"}),
        hint="6 位动态码",
    )
)
register(
    Factor(
        "email",
        "邮箱验证码",
        _email_available,
        _verify_email,
        sends_code=True,
        hint="6 位邮箱验证码",
    )
)
register(Factor("question", "安全问题", _question_available, _verify_question, hint="答案"))
register(
    Factor(
        "recovery",
        "恢复代码",
        _recovery_available,
        _verify_recovery,
        hint="10 位恢复代码",
    )
)
