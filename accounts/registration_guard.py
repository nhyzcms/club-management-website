"""注册查重（2026-10 需求，2026-10-24 调整）：用户名 / 邮箱 / 「姓名 + 校牌号」组合。

产品口径：同一个人只应有一个账号；重复注册往往是因为忘了原账号，直接引导去登录即可。
故命中时返回统一的 ``account_exists`` reason，并附命中的字段，前端据此提示
「请登录原账户」并把用户带回登录框。

**为什么真实姓名不单独判重**：校内同名同姓很常见（甚至同班），只按姓名拦会误伤真实
的新成员。姓名与校牌号**同时**一致才视为同一人；校牌号选填，没填则不参与判重
（见 docs/api/accounts.md 与本模块测试）。

实现边界：
- 用户名：大小写不敏感（与 Django 默认 User.username 唯一性一致的口径）。
- 邮箱：``User.email``（已认证绑定）或他人 email 通道 identifier（含 pending）。
- 姓名 + 校牌号：姓名 NFKC + 忽略空白比较；校牌号归一去空白、转大写
  （``member_roster.normalize_card_no``）。两者都命中才算重复。
  除 ``Profile.card_no`` 外也查**已绑定名册行** ``MemberIdentity.card_no``，覆盖
  「历史账号只绑了名册、资料里还没回写校牌号」的情况。
- 已注销账号（``Profile.deleted_at`` 非空）单独返回 ``deleted``，提示联系信息组——
  它们无法登录，直接说「请登录原账户」会让人卡死。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db.models import Q

from .member_roster import normalize_card_no
from .models import MemberIdentity, Profile, Verification

_WHITESPACE = re.compile(r"\s+")


def _name_variants(value: str) -> set[str]:
    """姓名的比较形态：NFKC 原文 / 折叠空白 / 去掉全部空白。

    「李　四」（全角空格）、「李 四」、「李四」都应视为同一个人；西文名保留空格时
    也能与原样入库的写法匹配。三个形态都拿去 ``iexact`` 查，命中任一即算同名。
    """
    nfkc = unicodedata.normalize("NFKC", value or "").strip()
    collapsed = _WHITESPACE.sub(" ", nfkc)
    compact = _WHITESPACE.sub("", nfkc)
    return {variant for variant in (nfkc, collapsed, compact) if variant}


def normalize_name(value: str) -> str:
    """姓名归一键（用于展示 / 精确匹配）：NFKC + 去掉全部空白。"""
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", value or "")).strip()


def _name_matches(stored: str, variants: set[str]) -> bool:
    return bool(_name_variants(stored) & variants)


def _card_variants(value: str) -> set[str]:
    """校牌号的数据库比较形态（覆盖原样 / 去空白大写）。"""
    raw = (value or "").strip()
    compact = normalize_card_no(raw)
    return {variant for variant in (raw, compact) if variant}


@dataclass(frozen=True)
class DuplicateAccount:
    """命中重复注册：``field`` 是 username / email / real_name_card_no 之一。"""

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


def _same_name_and_card(profile: Profile, name_variants: set[str], card_key: str) -> bool:
    return _name_matches(profile.real_name, name_variants) and (
        normalize_card_no(profile.card_no) == card_key
    )


def find_duplicate(
    *, username: str = "", real_name: str = "", card_no: str = "", email: str = "",
) -> DuplicateAccount | None:
    """按 用户名 → 邮箱 → 「姓名 + 校牌号」 的顺序查重，返回第一条命中。

    未填校牌号时**不做**姓名判重（同名学生可以各自注册；身份真伪由认证流程负责）。
    """
    username = (username or "").strip()
    email = (email or "").strip().lower()
    real_name = (real_name or "").strip()
    name_variants = _name_variants(real_name)
    card_key = normalize_card_no(card_no)

    if username:
        user = User.objects.filter(username__iexact=username).first()
        if user is not None:
            return DuplicateAccount("username", user, _deleted(user))

    if email:
        user = _email_owner(email)
        if user is not None:
            return DuplicateAccount("email", user, _deleted(user))

    if name_variants and card_key:
        name_filter = Q()
        for variant in name_variants:
            name_filter |= Q(real_name__iexact=variant)
        profiles = (
            Profile.objects.filter(name_filter)
            .select_related("user")
            .order_by("pk")
        )
        for profile in profiles:
            if _same_name_and_card(profile, name_variants, card_key):
                return DuplicateAccount(
                    "real_name_card_no", profile.user, bool(profile.deleted_at),
                )

        # 历史账号 / 后台手工绑定：名册行有校牌号但 Profile.card_no 尚未回写。
        card_filter = Q()
        for variant in _card_variants(card_no):
            card_filter |= Q(card_no__iexact=variant)
        rows = (
            MemberIdentity.objects.filter(card_filter, user__isnull=False)
            .select_related("user", "user__profile")
            .order_by("pk")
        )
        for row in rows:
            profile = getattr(row.user, "profile", None)
            # 行上的校牌号已由查询命中（覆盖 Profile.card_no 未回写的情况），
            # 这里只需确认姓名一致。
            if profile is not None and _name_matches(profile.real_name, name_variants):
                return DuplicateAccount(
                    "real_name_card_no", row.user, bool(profile.deleted_at),
                )

    return None


FIELD_LABELS = {
    "username": "用户名",
    "email": "邮箱",
    "real_name_card_no": "姓名 + 校牌号",
}


def duplicate_message(duplicate: DuplicateAccount) -> str:
    """给申请人的中文提示：已注销账号单独一句（无法登录，不要误导）。"""
    label = FIELD_LABELS.get(duplicate.field, "账号信息")
    if duplicate.deleted:
        return f"该{label}对应的账号已注销，无法登录。如有疑问请联系信息组。"
    return f"该{label}已注册，请登录原账户。"
