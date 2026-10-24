"""注册查重（2026-10 需求）：用户名 / 真实姓名 / 邮箱，命中任一即视为同一账户。

产品口径：同一个人只应有一个账号；重复注册往往是因为忘了原账号，直接引导去登录即可。
故命中时返回统一的 ``account_exists`` reason，并附命中的字段，前端据此提示
「请登录原账户」并把用户带回登录框。

实现边界：
- 用户名：大小写不敏感（与 Django 默认 User.username 唯一性一致的口径）。
- 邮箱：``User.email``（已认证绑定）或他人 email 通道 identifier（含 pending）。
- 真实姓名：NFKC + 折叠空白后大小写不敏感比较（中文名不受影响；西文名统一大小写）。
- 已注销账号（``Profile.deleted_at`` 非空）单独返回 ``deleted``，提示联系信息组——
  它们无法登录，直接说「请登录原账户」会让人卡死。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db.models import Q

from .models import Profile, Verification

_WHITESPACE = re.compile(r"\s+")


def _name_variants(value: str) -> set[str]:
    """姓名的比较形态：NFKC 原文 / 折叠空白 / 去掉全部空白。

    「李　四」（全角空格）、「李 四」、「李四」都应视为同一个人；西文名保留空格时
    也能与原样入库的写法匹配。三个形态都拿去 ``iexact`` 查，命中任一即算重复。
    """
    nfkc = unicodedata.normalize("NFKC", value or "").strip()
    collapsed = _WHITESPACE.sub(" ", nfkc)
    compact = _WHITESPACE.sub("", nfkc)
    return {variant for variant in (nfkc, collapsed, compact) if variant}


def normalize_name(value: str) -> str:
    """姓名归一键（用于展示 / 精确匹配）：NFKC + 去掉全部空白。"""
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", value or "")).strip()


@dataclass(frozen=True)
class DuplicateAccount:
    """命中重复注册：``field`` 是 username / email / real_name 之一。"""

    field: str
    user: User
    deleted: bool = False


def _email_owner(email: str) -> User | None:
    user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        return user
    verification = (
        Verification.objects.filter(
            channel=Verification.CHANNEL_EMAIL,
            identifier__iexact=email,
            status__in=[Verification.STATUS_PENDING, Verification.STATUS_APPROVED],
        )
        .select_related("user")
        .first()
    )
    return verification.user if verification is not None else None


def _deleted(user: User) -> bool:
    profile = Profile.objects.filter(user=user).only("deleted_at").first()
    return bool(profile and profile.deleted_at)


def find_duplicate(
    *, username: str = "", real_name: str = "", email: str = "",
) -> DuplicateAccount | None:
    """按 用户名 → 邮箱 → 真实姓名 的顺序查重，返回第一条命中（无命中返回 None）。"""
    username = (username or "").strip()
    email = (email or "").strip().lower()
    real_name = (real_name or "").strip()
    name_variants = _name_variants(real_name)

    if username:
        user = User.objects.filter(username__iexact=username).first()
        if user is not None:
            return DuplicateAccount("username", user, _deleted(user))

    if email:
        user = _email_owner(email)
        if user is not None:
            return DuplicateAccount("email", user, _deleted(user))

    if name_variants:
        name_filter = Q()
        for variant in name_variants:
            name_filter |= Q(real_name__iexact=variant)
        profile = (
            Profile.objects.filter(name_filter)
            .select_related("user")
            .order_by("pk")
            .first()
        )
        if profile is not None:
            return DuplicateAccount("real_name", profile.user, bool(profile.deleted_at))

    return None


FIELD_LABELS = {
    "username": "用户名",
    "email": "邮箱",
    "real_name": "真实姓名",
}


def duplicate_message(duplicate: DuplicateAccount) -> str:
    """给申请人的中文提示：已注销账号单独一句（无法登录，不要误导）。"""
    label = FIELD_LABELS.get(duplicate.field, "账号信息")
    if duplicate.deleted:
        return f"该{label}对应的账号已注销，无法登录。如有疑问请联系信息组。"
    return f"该{label}已注册，请登录原账户。"
