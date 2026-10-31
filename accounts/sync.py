"""``Profile`` → ``AccountIdentity`` / ``AccountLifecycle`` 的双写（B4 PR 2a）。

PR 1 建了新表并回填，但刻意不动写路径——所以新表会逐渐落后于 ``Profile``。
本模块补上双写：``Profile.save()`` 之后把 8 个字段同步到新表。

**为什么覆盖 ``save()`` 而不是接 ``post_save`` 信号**

两者覆盖面相同（都拦不住 ``queryset.update()``），但覆盖 ``save()`` 是显式的：
读 ``Profile`` 的代码就能看到同步逻辑。信号挂在 ``apps.ready()`` 里，后人删掉
一行 import 就静默失效，而测试通常发现不了——数据只是慢慢变旧。

**为什么不用 ``queryset.update()`` 钩子**

Django 没有这种钩子。生产代码里没有 ``Profile.objects.filter(...).update(...)``
（全仓只有 3 处，都在测试里且不关心新表），所以不需要处理。

**为什么不包事务**

``save()`` 可能已在调用方的事务里。这里再包一层 ``atomic`` 会改变嵌套语义，
而且一旦同步失败就整笔回滚——把「影子表写失败」升级成「用户改资料失败」，
方向错了。当前策略是：同步失败直接抛，让调用方感知，宁可报错不要静默漂移。
"""
from __future__ import annotations


def sync_from_profile(profile):
    """把 ``Profile`` 的 8 个字段写到新表（幂等）。

    迁移回填覆盖存量、``Profile.save()`` 覆盖增量，两者合起来保证 PR 3 删旧列
    时新表不丢数据。
    """
    # 延迟 import：models.py 会在 Profile.save() 里调用本函数，模块级 import 会成环
    from .models import AccountIdentity, AccountLifecycle

    if profile is None or profile.pk is None or profile.user_id is None:
        return

    AccountIdentity.objects.update_or_create(
        user_id=profile.user_id,
        defaults={
            "real_name": profile.real_name or "",
            "identity": profile.identity or "",
            # 唯一改了名的列：Profile.card_no → AccountIdentity.pending_card_no
            "pending_card_no": profile.card_no or "",
        },
    )
    AccountLifecycle.objects.update_or_create(
        user_id=profile.user_id,
        defaults={
            "registration_deadline": profile.registration_deadline,
            "expiry_disabled_at": profile.expiry_disabled_at,
            "deleted_at": profile.deleted_at,
            "validity_notice_ack": profile.validity_notice_ack or "",
            "must_change_password": profile.must_change_password,
        },
    )


def backfill_all():
    """把全量 ``Profile`` 同步到新表。用于 PR 2 部署后的对齐（也可在 shell 里跑）。"""
    from .models import Profile

    count = 0
    for profile in Profile.objects.all().iterator():
        sync_from_profile(profile)
        count += 1
    return count
