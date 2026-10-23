"""识别码生成与扫码签名（社员身份编号系统，见 ADR-0025）。

识别码 = 8 位数字：
``[入学年份后 2 位][首次入社届数 2 位][姓名排序序号 2 位][校验码 2 位]``，例：``26020542``。

- **姓名排序序号**：按**当次导入名单**的姓名 GBK 编码序分配（GB2312 一级字 3755 个按拼音
  排列，常用姓名≈拼音序；生僻字按部首会偏），01 起、单届上限 99；同届追加导入接续
  已有最大序号（不重排已发码）；重复导入按身份键认行、保留原码。
- **校验码**：ISO 7064 MOD 97-10——``check = 98 - (前 6 位 × 100 mod 97)``，
  完整 8 位数 ``mod 97 == 1``；手输 / 抄录错误可被自检发现。
- 全库唯一由数据库约束兜底；表格中的「识别码」列内容忽略——编码一律走本生成器。

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

MAX_SERIAL = 99
SIG_HEX_LEN = 16

_CODE_RE = re.compile(r"^[0-9A-Za-z-]{4,16}$")


class MemberCodeError(Exception):
    """识别码生成失败（届内序号用尽等）。"""


def code_prefix(admit_year: int, cohort: int) -> str:
    """识别码前 4 位：[入学年份后 2 位][首次入社届数 2 位]。"""
    return f"{admit_year % 100:02d}{cohort:02d}"


def check_digits(six: str) -> str:
    """ISO 7064 MOD 97-10 的两位校验码（入参 = 前 6 位数字）。"""
    return f"{98 - (int(six) * 100) % 97:02d}"


def compose_code(six: str) -> str:
    """前 6 位 + 两位校验码 = 完整 8 位识别码。"""
    return f"{six}{check_digits(six)}"


def verify_code_checksum(code: str) -> bool:
    """8 位数字识别码的校验位自检（完整码 ``mod 97 == 1``）。"""
    code = (code or "").strip()
    if len(code) != 8 or not code.isdigit():
        return False
    return int(code) % 97 == 1


def generate_code(admit_year: int, cohort: int, serial: int) -> str:
    """按 (入学年份, 首次入社届数, 姓名排序序号) 生成识别码（序号 01-99）。"""
    if not 1 <= serial <= MAX_SERIAL:
        raise MemberCodeError(f"届内序号超出范围（1-{MAX_SERIAL}，收到 {serial}）")
    return compose_code(f"{code_prefix(admit_year, cohort)}{serial:02d}")


def next_serial(admit_year: int, cohort: int, taken: set[str]) -> int:
    """该届下一个可用序号（接续已有最大序号；空届从 1 起，超上限抛错）。

    ``taken`` 为当前已占用的识别码集合（库内 + 本批已分配）。
    """
    prefix = code_prefix(admit_year, cohort)
    used = [
        int(c[4:6])
        for c in taken
        if len(c) == 8 and c.isdigit() and c.startswith(prefix) and 1 <= int(c[4:6]) <= MAX_SERIAL
    ]
    serial = (max(used) + 1) if used else 1
    if serial > MAX_SERIAL:
        raise MemberCodeError(f"该届序号已用尽（上限 {MAX_SERIAL}，前缀 {prefix}）")
    return serial


def name_sort_key(name: str) -> bytes:
    """姓名排序键：GBK 编码序（GB2312 一级字按拼音排列；生僻字退化为 UTF-8 码点序）。"""
    text = name or ""
    try:
        return text.encode("gbk")
    except UnicodeEncodeError:
        return text.encode("utf-8")


def is_valid_code(code: str) -> bool:
    """识别码的形状校验（4-16 位数字/字母/短横线；不校验完整规则）。"""
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
