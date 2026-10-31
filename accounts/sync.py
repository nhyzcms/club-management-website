"""保证每个 ``Profile`` 都有对应的 ``AccountIdentity`` / ``AccountLifecycle`` 行。

## 历史

PR 2a（#219）时本模块是**双写**：``Profile.save()`` 之后把 8 个字段同步到新表。
那是迁移期的临时状态——``Profile`` 是权威，新表是镜像。

PR 3b2 删掉旧列后关系反转：**新表是唯一真源**。本模块只剩一件事：新建 ``Profile``
时补上新表行。

## 为什么删了旧列还要挂 save()

``Profile.save()`` 已经没有字段可同步，但**注册流程仍然先建 ``Profile``**。
如果不补行，新注册用户在新表里就没有记录——``lifecycle_q`` 的 INNER JOIN 会把他
从名册、登录校验、注销判定里全部漏掉。这类缺失不会报错，只会让「刚注册的人查不到」。

## 为什么用 get_or_create 而不是 update_or_create

新表是权威。``save()`` 也发生在更新展示资料（头像 / 昵称 / 简介）的时候，那时绝不该
碰生命周期字段。只补行，不覆盖值。

想同步值请直接写 ``AccountIdentity`` / ``AccountLifecycle`` 本身。
"""
from __future__ import annotations


def ensure_split_rows(profile):
    """确保 ``profile.user`` 在两张新表里都有行（幂等，不覆盖已有值）。"""
    # 延迟 import：models.py 会在 Profile.save() 里调用本函数，模块级 import 会成环
    from .models import AccountIdentity, AccountLifecycle

    if profile is None or profile.pk is None or profile.user_id is None:
        return

    AccountIdentity.objects.get_or_create(user_id=profile.user_id)
    AccountLifecycle.objects.get_or_create(user_id=profile.user_id)
