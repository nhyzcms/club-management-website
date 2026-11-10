"""账号状态的单一真源（B4）。

**收敛前的状况**：「账号能不能用」由四处各自判断——

- ``models.is_deleted_user(user)``（只判注销）
- ``views.py`` 的登录提示（``Profile.objects.filter(expiry_disabled_at__isnull=False)``）
- ``accounts/deletion.py``（又判一次注销）
- ``validity_summary.py``（算有效期，隐含「超期 = 不能用」）

四处各自读 ``Profile``，谁也没覆盖全部情形。比如「管理员手动停用」在登录提示
里根本没被单独识别——用户只会看到 Django 默认的「账号已停用」。

**状态定义**：只有四个能到达的状态。计划里原本还列了 ``inactive``，但当前系统
``is_active=False`` 只有两个来源：超期自动停用（带 ``expiry_disabled_at`` 标记）
和管理员手动停用。没有第三种。留一个不可达的状态，只会让调用方以为要处理它。

**优先级**：注销 > 超期停用 > 管理员停用 > 可用。

优先级不是拍脑袋：生产实测有一个用户 ``is_active=False`` **且** ``deleted_at``
非空。若先判 ``is_active``，他会被告知「账号已被管理员停用」——而真相是他自己
注销了。先判注销才对。
"""
from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist

ACTIVE = "active"
DELETED = "deleted"
UNVERIFIED_EXPIRED = "unverified_expired"
ADMIN_EXPIRED = "admin_expired"

STATE_LABELS = {
    ACTIVE: "正常",
    DELETED: "已注销",
    UNVERIFIED_EXPIRED: "注册超期未认证",
    ADMIN_EXPIRED: "已被管理员停用",
}


def lifecycle_of(user):
    """取 ``AccountLifecycle``；缺行返回 ``None``。

    B4 PR 3b2 之前这里还要回落 ``Profile`` 的旧列。旧列删掉后回落失去意义，
    只剩新表——两道保险保证不会缺行（``0035`` 迁移补齐存量、``Profile.save()``
    补新增），所以缺行 = 数据异常，调用方按「无标记」处理，与历史行为一致。
    """
    try:
        return user.lifecycle
    except ObjectDoesNotExist:
        return None


def account_state(user):
    """返回 ``(state, reason)``。

    ``state`` ∈ ``{active, deleted, unverified_expired, admin_expired}``，
    ``reason`` 是给人看的说明（``active`` 时为空串）。

    只读缓存/关联，不额外查询：``user.lifecycle`` 是 OneToOne 反向访问器，
    Django 会缓存在 ``_state.fields_cache``。
    """
    source = lifecycle_of(user)

    def field(name):
        return getattr(source, name, None) if source is not None else None

    # 1. 注销优先：注销用户 is_active 通常也已置 False，先判 is_active 会误报
    if field("deleted_at") is not None:
        return DELETED, "账号已注销"

    # 2. 超期未认证停用（系统自动，带标记）
    if field("expiry_disabled_at") is not None:
        return UNVERIFIED_EXPIRED, "注册后未在宽限期内完成认证，账号已停用"

    # 3. 管理员手动停用（is_active=False 且无超期标记）
    if not user.is_active:
        return ADMIN_EXPIRED, "账号已被管理员停用"

    return ACTIVE, ""


def is_usable(user):
    """账号当前是否可用。等价于 ``account_state(user)[0] == ACTIVE``。"""
    return account_state(user)[0] == ACTIVE


def needs_password_change(user) -> bool:
    """是否处于「管理员重置后必须改密」状态（缺行视为否）。"""
    lifecycle = lifecycle_of(user)
    return bool(lifecycle.must_change_password) if lifecycle is not None else False


def set_needs_password_change(user, value: bool) -> None:
    """设置强制改密标记。缺行时先补行（``Profile.save()`` 正常会补，这里是兜底）。"""
    from .models import AccountLifecycle

    lifecycle = lifecycle_of(user)
    if lifecycle is None:
        lifecycle, _ = AccountLifecycle.objects.get_or_create(user=user)
    lifecycle.must_change_password = value
    lifecycle.save(update_fields=["must_change_password"])
