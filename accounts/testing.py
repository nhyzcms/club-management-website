"""B4 之后的测试夹具助手。

## 为什么需要

``Profile`` 不再有实名 / 生命周期字段（PR 3b2 删了 8 个旧列），测试里常见的

```python
Profile.objects.create(user=u, real_name="张三", deleted_at=now)
```

会抛 ``TypeError: Profile() got unexpected keyword arguments``。

``make_profile()`` 是等价写法：先建 ``Profile``（``save()`` 会自动带出两张新表的行），
再把字段写到对应的新表。

## 为什么不直接改测试里的每一行

28 处调用点分散在 17 个文件，每处都要「建 Profile → 写新表 → 保持原返回值」三步。
集中成一个函数比散落 28 份样板更好维护——将来再加字段只改这里。

## card_no 的映射

``Profile.card_no`` → ``AccountIdentity.pending_card_no``。这是 B4 里唯一改名的列，
测试写 ``card_no=`` 时自动映射，避免每个调用点都记住新名字。
"""
from .models import AccountIdentity, AccountLifecycle, Profile

_IDENTITY_FIELDS = {"real_name", "identity", "card_no"}
_LIFECYCLE_FIELDS = {
    "registration_deadline",
    "expiry_disabled_at",
    "deleted_at",
    "validity_notice_ack",
    "must_change_password",
}
# 仍在 Profile 上的展示字段，直接透传给 create()
_PROFILE_FIELDS = {"avatar", "nickname", "birthday", "gender", "bio"}


def make_profile(user, **fields):
    """建 ``Profile`` 并写入实名 / 生命周期字段（B4 之后的等价写法）。

    字段名沿用旧名（``card_no`` 而非 ``pending_card_no``），内部自动映射。
    展示字段（``nickname`` / ``bio`` 等）直接透传给 ``Profile.objects.create()``。
    未知字段直接抛 ``TypeError``——静默忽略会让测试以为设了值其实没设。
    """
    unknown = set(fields) - _IDENTITY_FIELDS - _LIFECYCLE_FIELDS - _PROFILE_FIELDS
    if unknown:
        raise TypeError(f"make_profile 不认识这些字段：{sorted(unknown)}")

    profile_fields = {k: v for k, v in fields.items() if k in _PROFILE_FIELDS}
    profile = Profile.objects.create(user=user, **profile_fields)

    identity = {k: v for k, v in fields.items() if k in _IDENTITY_FIELDS}
    if "card_no" in identity:
        identity["pending_card_no"] = identity.pop("card_no")
    if identity:
        AccountIdentity.objects.filter(user=user).update(**identity)

    lifecycle = {k: v for k, v in fields.items() if k in _LIFECYCLE_FIELDS}
    if lifecycle:
        AccountLifecycle.objects.filter(user=user).update(**lifecycle)

    # ``Profile.objects.create()`` 触发的 ``ensure_split_rows()`` 会把两行读进
    # ``user._state.fields_cache``。之后用 ``.update()`` 写的值不会刷新那个缓存，
    # 调用方 ``user.identity_record.real_name`` 会读到空值。必须手动清掉。
    _drop_cache(user)
    return profile


def _drop_cache(user):
    """清掉 ``user`` 上 OneToOne 反向访问器的缓存，强制下次重新查询。"""
    cache = getattr(getattr(user, "_state", None), "fields_cache", None)
    if cache is None:
        return
    for name in ("identity_record", "lifecycle", "profile"):
        cache.pop(name, None)
