"""识别码生成与扫码签名（社员身份编号系统，见 ADR-0025）。

识别码 = 8 位数字：
``[入学年份后 2 位][首次入社届数 2 位][姓名排序序号 2 位][校验码 2 位]``，例：``26020251``。

- **姓名排序序号**：按**当次导入名单**的姓名**拼音首字母**分配（多音字姓氏按姓氏读音，
  如 单 shàn→S、解 xiè→X、查 zhā→Z；同首字母内按 GBK 编码序细排——GB2312 一级字
  3755 个本身按拼音排列），01 起、单届上限 99；同届追加导入**接续**已有最大序号
  （不重排已发码，续号内部仍按首字母排）；重复导入按身份键认行、保留原码。
  首字母判定见 ``accounts/name_order.py``（零依赖）。
- **校验码**：ISO 7064 MOD 97-10——``check = 98 - (前 6 位 × 100 mod 97)``，
  完整 8 位数 ``mod 97 == 1``；手输 / 抄录错误可被自检发现。
- **校验码的避讳规则**（2026-10-24 起的民俗偏好）：后两位（校验码）**任意位置出现
  2 或 4 一律不用**，末位另避开 0。「校验码由前 6 位唯一决定」，所以不能直接挑一个
  好看的校验值，只能在**分配序号**时跳号——逐个试算序号，跳过会算出「含 2/4 或末位 0」
  的号（见 ``next_serial``）。代价是每届 99 个序号里约 55 个可用、序号会出现空洞；
  **已发码不重排**（``renumber_member_codes`` 命令可整批重算，需人工确认）。
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

from .name_order import name_sort_key  # 排序键实现见 name_order.py（首字母 + GBK 序）

MAX_SERIAL = 99
SIG_HEX_LEN = 16

# 校验码（识别码后两位）的避讳：任意位置出现 2 / 4 一律跳过；
# 末位另避开 0（民俗偏好）。校验码由前 6 位唯一决定，只能靠 next_serial() 跳号实现。
UNLUCKY_CHECK_DIGITS = frozenset("24")
UNLUCKY_LAST_DIGITS = frozenset("024")

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


def is_preferred_code(code: str) -> bool:
    """识别码的校验码是否符合避讳规则（不含 2/4，且末位不是 0）。

    只用于**分配新码**时的筛选；历史码不保证满足，界面上也不要拿它当「非法」提示。
    """
    code = (code or "").strip()
    if len(code) != 8 or not code.isdigit():
        return False
    tail = code[6:]
    if UNLUCKY_CHECK_DIGITS & set(tail):
        return False
    return tail[-1] not in UNLUCKY_LAST_DIGITS


def generate_code(admit_year: int, cohort: int, serial: int) -> str:
    """按 (入学年份, 首次入社届数, 姓名排序序号) 生成识别码（序号 01-99）。"""
    if not 1 <= serial <= MAX_SERIAL:
        raise MemberCodeError(f"届内序号超出范围（1-{MAX_SERIAL}，收到 {serial}）")
    return compose_code(f"{code_prefix(admit_year, cohort)}{serial:02d}")


def next_serial(admit_year: int, cohort: int, taken: set[str]) -> int:
    """该届下一个可用序号（接续已有最大序号，并让校验码符合避讳规则）。

    ``taken`` 为当前已占用的识别码集合（库内 + 本批已分配）。
    校验码由前 6 位唯一决定，无法直接「挑一个好看的校验值」，因此这里逐个试算序号、
    跳过校验码含 2/4 或末位为 0 的号（会在序号序列里留下空洞）。
    99 个序号中约 55 个可用；全部不合规则抛 ``MemberCodeError``。
    """
    prefix = code_prefix(admit_year, cohort)
    used = [
        int(c[4:6])
        for c in taken
        if len(c) == 8 and c.isdigit() and c.startswith(prefix) and 1 <= int(c[4:6]) <= MAX_SERIAL
    ]
    start = (max(used) + 1) if used else 1
    for serial in range(start, MAX_SERIAL + 1):
        if is_preferred_code(generate_code(admit_year, cohort, serial)):
            return serial
    raise MemberCodeError(
        f"该届序号已用尽（上限 {MAX_SERIAL}；校验码避开 2/4、末位避开 0 后每届约 55 个可用，前缀 {prefix}）"
    )


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
