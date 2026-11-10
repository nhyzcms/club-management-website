"""TOTP（RFC 6238）与恢复代码：滚动密钥的全部密码学细节。

- 算法：HMAC-SHA1 / 30 秒 / 6 位（与 Google Authenticator、Microsoft Authenticator 兼容）
- 校验允许 ±1 个时间窗（时钟漂移），`last_used_step` 防重放（同一步长只能用一次）
- secret 用 Fernet 加密后入库（key 由 SECRET_KEY 派生），明文只在 setup 响应里出现一次
- 恢复代码只存 sha256，一次性
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings

DIGITS = 6
PERIOD = 30
WINDOW = 1
MAX_TOTP_DEVICES = 5
# 新建但还没输码确认的临时记录：超过上限时只清「旧」的，保证正在扫的那条二维码不被误删。
MAX_PENDING_TOTP = 3
PENDING_TTL_MINUTES = 10
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_LENGTH = 10

# 去掉 O/0/I/1 这类容易抄错的字符
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_secret() -> str:
    """20 字节随机 → base32（160 bit，标准 TOTP 长度）。"""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.strip().upper()
    padded += "=" * (-len(padded) % 8)
    return base64.b32decode(padded)


def hotp(secret: str, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def step_at(ts: float | None = None) -> int:
    return int((time.time() if ts is None else ts) // PERIOD)


def code_at(secret: str, ts: float | None = None) -> str:
    return hotp(secret, step_at(ts))


def verify(secret: str, code: str, last_step: int = 0, at: float | None = None) -> int | None:
    """校验 6 位码：命中返回时间步，否则 None。

    ``last_step`` 之前的步一律拒绝——同一个码不能用第二次（重放保护）。
    """
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = step_at(at)
    for delta in (-WINDOW, 0, WINDOW):
        step = current + delta
        if step <= last_step:
            continue
        if hmac.compare_digest(hotp(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account_name: str, issuer: str = "南汇一中传媒社") -> str:
    label = quote(f"{issuer}:{account_name}")
    params = "&".join(
        [
            f"secret={secret}",
            f"issuer={quote(issuer)}",
            "algorithm=SHA1",
            f"digits={DIGITS}",
            f"period={PERIOD}",
        ]
    )
    return f"otpauth://totp/{label}?{params}"


# ---- secret 加密（Fernet，key 由 SECRET_KEY 派生）----


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(
        hashlib.sha256(f"{settings.SECRET_KEY}:totp".encode()).digest()
    )
    return Fernet(key)


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


# ---- 恢复代码 ----


def generate_recovery_codes(
    count: int = RECOVERY_CODE_COUNT, length: int = RECOVERY_CODE_LENGTH
) -> list[str]:
    return [
        "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(length))
        for _ in range(count)
    ]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()
