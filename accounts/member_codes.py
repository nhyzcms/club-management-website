"""识别码生成与扫码签名（社员身份编号系统，见 ADR-0025）。

识别码 = 8 位数字：
``[入学年份后 2 位][首次入社届数 2 位][姓名排序序号 2 位][校验码 2 位]``，例：``26020542``。

- **姓名排序序号**：按**当次导入名单**的姓名**拼音首字母**分配（多音字姓氏按姓氏读音，
  如 单 shàn→S、解 xiè→X、查 zhā→Z；同首字母内按 GBK 编码序细排——GB2312 一级字
  3755 个本身按拼音排列），01 起、单届上限 99；同届追加导入**接续**已有最大序号
  （不重排已发码，续号内部仍按首字母排）；重复导入按身份键认行、保留原码。
  首字母判定见 ``accounts/name_order.py``（零依赖）。
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

from .name_order import name_sort_key  # 排序键实现见 name_order.py（首字母 + GBK 序）

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


# ---- 条形码载荷（12 位：6 位唯一键 + 6 位十进制短签名）----
#
# 条码长度是硬约束：Code128C 每 2 位数字占 11 模块，起始/校验/终止另占 35 模块。
# 所以载荷要尽量短：
#
#   - **只带前 6 位**：``[入学年份后 2 位][届数 2 位][序号 2 位]`` 本身唯一，
#     末 2 位是 ISO 7064 校验位、专供手抄自检——条码由机器读（Code128 自带
#     模 103 校验符），服务端反查后重算即可；
#   - **签名降为 6 位十进制**：16 位 hex 会把条码撑到 255 模块（≈84mm），且字母
#     会从 Code128C 掉回 Code128B（宽度翻倍、抗模糊骤降）；纯数字才留在 C 集合。
#     6 位 = 10^6 空间，配合端点限流足以挡住「猜载荷遍历」。
#   - **域分离**：HMAC 输入加 ``barcode:`` 前缀，与二维码的 16 位 hex 签名互不通用。
BARCODE_SIG_DIGITS = 6
BARCODE_SIG_DOMAIN = "barcode:"


def make_barcode_signature(code: str) -> str:
    """条形码短签名：HMAC-SHA256(密钥, ``barcode:<识别码>``) 取前 8 字节 mod 10^6。"""
    mac = hmac.new(
        _secret(), f"{BARCODE_SIG_DOMAIN}{code or ''}".encode(), hashlib.sha256
    ).digest()
    value = int.from_bytes(mac[:8], "big") % 10 ** BARCODE_SIG_DIGITS
    return str(value).zfill(BARCODE_SIG_DIGITS)


def verify_barcode_signature(code: str, sig: str) -> bool:
    if not code or not sig:
        return False
    return hmac.compare_digest(make_barcode_signature(code), (sig or "").strip())


def barcode_payload(code: str) -> str:
    """条形码载荷：6 位唯一键 + 6 位短签名（共 12 位数字）。

    例：识别码 ``26020542`` → 载荷 ``260205`` + 签名。
    """
    code = (code or "").strip()
    if len(code) != 8 or not code.isdigit():
        raise MemberCodeError(f"识别码格式不正确：{code!r}")
    return f"{code[:6]}{make_barcode_signature(code)}"


def split_barcode_payload(payload: str) -> tuple[str, str] | None:
    """12 位载荷 → (6 位唯一键, 6 位签名)；形状不对返回 None。"""
    text = (payload or "").strip()
    if len(text) != 6 + BARCODE_SIG_DIGITS or not text.isdigit():
        return None
    return text[:6], text[6:]
