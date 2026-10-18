"""识别码生成与扫码签名（社员身份编号系统，见 ADR-0025）。

识别码 = 8 位数字：[入学年份后 2 位][届数 2 位][届内序号 4 位]，例：``26020001``。

- 届内序号从 ``0001`` 起，取该届**第一个空位**（导入 / 补号时确定性分配，重复导入稳定）；
- 全库唯一由数据库约束兜底；生成器只负责给候选，不判断入库成败；
- 表格中的「识别码」列内容忽略——编码一律走本生成器（2026-10-18 修订）。

扫码签名：二维码内容 = ``{FRONTEND_URL}/#/v/<码>?s=<签名>``，
签名 = HMAC-SHA256(站点密钥, 识别码) 截断 16 位 hex——防止对公开校验端点的
「猜码遍历」（识别码是结构化数字，裸编号可被枚举）。密钥默认由 ``SECRET_KEY``
派生，可用环境变量 ``MEMBER_QR_SECRET`` 覆盖。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

from django.conf import settings

MAX_SERIAL = 9999
SIG_HEX_LEN = 16

_CODE_RE = re.compile(r"^[0-9A-Za-z-]{4,16}$")


class MemberCodeError(Exception):
    """识别码生成失败（届内序号用尽等）。"""


def code_prefix(admit_year: int, cohort: int) -> str:
    """识别码前 4 位：[入学年份后 2 位][届数 2 位]。"""
    return f"{admit_year % 100:02d}{cohort:02d}"


def generate_code(admit_year: int, cohort: int, taken: set[str]) -> str:
    """为 (入学年份, 届数) 的成员生成该届内第一个空位识别码。

    ``taken`` 为当前已占用的识别码集合（含库内 + 本批已分配）。
    """
    prefix = code_prefix(admit_year, cohort)
    for serial in range(1, MAX_SERIAL + 1):
        candidate = f"{prefix}{serial:04d}"
        if candidate not in taken:
            return candidate
    raise MemberCodeError(f"届内序号已用尽（前缀 {prefix}）")


def is_valid_code(code: str) -> bool:
    """自带识别码的形状校验（4-16 位数字/字母/短横线）。"""
    return bool(_CODE_RE.match((code or "").strip()))


def _secret() -> bytes:
    raw = os.environ.get("MEMBER_QR_SECRET")
    if raw:
        return raw.encode()
    return hashlib.sha256(f"{settings.SECRET_KEY}:member-qr".encode()).digest()


def make_signature(code: str) -> str:
    return hmac.new(_secret(), (code or "").encode(), hashlib.sha256).hexdigest()[:SIG_HEX_LEN]


def verify_signature(code: str, sig: str) -> bool:
    if not code or not sig:
        return False
    return hmac.compare_digest(make_signature(code), sig.strip().lower())


def build_verify_url(code: str) -> str:
    """二维码承载的校验页 URL（HashRouter 路由，无需服务器改动）。"""
    return f"{settings.FRONTEND_URL}/#/v/{code}?s={make_signature(code)}"
