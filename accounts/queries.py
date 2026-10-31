"""B4 PR 2b：把「生命周期字段」的 queryset 过滤切到新表，且**不改变结果集**。

## 为什么需要这一层

`Profile.objects.filter(deleted_at__isnull=True)` 拼的是 SQL 列名，绕不过 ORM 的
property——所以要切到新表，只能改查询本身：

```python
Profile.objects.filter(user__lifecycle__deleted_at__isnull=True)   # 直觉写法，但是错的
```

**错在哪**：`user__lifecycle` 是 INNER JOIN。新表没有行的用户（PR 1 之后、PR 2a
之前注册的历史用户，或任何回填遗漏）会被**直接排除**。

旧写法 `filter(deleted_at__isnull=True)` 会**包含**他。

方向反了：把可用用户从名册里排除，比把注销用户包含进来更糟——前者是数据消失，
后者只是多显示一行。

## 做法

新表有行 → 看新表；新表缺行 → 回落旧列。与 B1 的 `related_to` 同一个思路：

```python
Q(user__lifecycle__isnull=False) & Q(user__lifecycle__deleted_at__isnull=True)   # 新表有行
| Q(user__lifecycle__isnull=True) & Q(deleted_at__isnull=True)                   # 缺行回落
```

PR 3 删掉 `Profile` 的旧列后，回落分支会变成无效条件（列不存在），届时删除即可。
"""
from __future__ import annotations

from django.db.models import Q


def lifecycle_q(field, *, value=None, isnull=None):
    """构造「新表优先 + 缺行回落旧列」的 ``Q``。

    ``field`` 是 ``AccountLifecycle`` 与 ``Profile`` **同名**的字段：
    ``deleted_at`` / ``expiry_disabled_at`` / ``registration_deadline`` /
    ``validity_notice_ack`` / ``must_change_password``。

    只能用同名且语义相同的字段。``card_no`` 不在此列——它在新表叫
    ``pending_card_no`` 且语义变了（「待绑定」而非「校牌号」），不能这样回落。
    """
    if (value is None) == (isnull is None):
        raise ValueError("lifecycle_q 需要 value 或 isnull 恰好一个")

    suffix = {}
    if value is not None:
        suffix[""] = value
    else:
        suffix["__isnull"] = isnull

    new_branch = Q(user__lifecycle__isnull=False)
    old_branch = Q(user__lifecycle__isnull=True)
    for sfx, val in suffix.items():
        new_branch &= Q(**{f"user__lifecycle__{field}{sfx}": val})
        old_branch &= Q(**{f"{field}{sfx}": val})
    return new_branch | old_branch


def not_deleted_q():
    """「未注销」——等价于旧的 ``deleted_at__isnull=True``。"""
    return lifecycle_q("deleted_at", isnull=True)


def deleted_q():
    """「已注销」——等价于旧的 ``deleted_at__isnull=False``。"""
    return lifecycle_q("deleted_at", isnull=False)


def expiry_disabled_q():
    """「因超期停用」——等价于旧的 ``expiry_disabled_at__isnull=False``。"""
    return lifecycle_q("expiry_disabled_at", isnull=False)


def must_change_password_q():
    """「需强制改密」——等价于旧的 ``must_change_password=True``。"""
    return lifecycle_q("must_change_password", value=True)


def identity_q(field, **lookup):
    """构造「``AccountIdentity`` 优先 + 缺行回落旧列」的 ``Q``。

    ``field`` 必须是两边**同名且语义相同**的字段：``real_name`` / ``identity``。

    **不包括 ``card_no``** —— 它在新表叫 ``pending_card_no``，语义也从「校牌号」
    变成了「待绑定暂存」（B4 PR 3a）。混用会让「已绑定用户」的查询意外命中，
    而绑定之后暂存本该是空的。

    用法::

        Profile.objects.filter(identity_q("real_name", iexact=name))
        Profile.objects.filter(identity_q("real_name", contains=kw))
    """
    if not lookup:
        raise ValueError("identity_q 至少需要一个查询条件")

    new_branch = Q(user__identity_record__isnull=False)
    old_branch = Q(user__identity_record__isnull=True)
    for sfx, val in lookup.items():
        new_branch &= Q(**{f"user__identity_record__{field}__{sfx}": val})
        old_branch &= Q(**{f"{field}__{sfx}": val})
    return new_branch | old_branch
