"""删掉 ``Profile`` 上被 B4 拆走的 8 个旧列。

## 为什么可以删

- 0034 建了 ``AccountIdentity`` / ``AccountLifecycle`` 并双向回填
- 2a（#219）起 ``Profile.save()`` 双写，新表跟得上
- 2b（#220）/ 3b1（#223）把 queryset 过滤全部切到新表
- 3a（#222）把校牌号权威归一

## 为什么还要在迁移里再补一次

双写覆盖所有走 ``save()`` 的写点，但**覆盖不了「0034 之后、2a 之前创建的行」**——
那段窗口里 ``Profile.save()`` 还不写新表。生产上这段时间可能有新用户注册。

所以删列前先补一次：新表缺行的用户，用旧列的值填进去。

**这一步放在迁移里，而不是依赖运维记得跑 ``check_profile_sync``。** 删列不可逆，
保险不能挂在流程上——流程会被跳过，迁移不会。

## 反向

``RemoveField`` 的反向是 ``AddField``（空默认值），所以必须自己写回填，
否则回滚后 8 个字段全是空——看起来「迁移成功」，数据却没了。

Django 反向执行 operations 的**逆序**：先 ``AddField`` ×8，再跑本函数的 reverse，
所以反向回填时列一定存在。
"""
from django.db import migrations


IDENTITY_MAP = [
    ("real_name", "real_name"),
    ("identity", "identity"),
    ("card_no", "pending_card_no"),  # 唯一改名的列
]
LIFECYCLE_MAP = [
    ("registration_deadline", "registration_deadline"),
    ("expiry_disabled_at", "expiry_disabled_at"),
    ("deleted_at", "deleted_at"),
    ("validity_notice_ack", "validity_notice_ack"),
    ("must_change_password", "must_change_password"),
]


def ensure_split_complete(apps, schema_editor):
    """删列前补齐「新表缺行」的用户——否则删列即丢数据。"""
    Profile = apps.get_model("accounts", "Profile")
    AccountIdentity = apps.get_model("accounts", "AccountIdentity")
    AccountLifecycle = apps.get_model("accounts", "AccountLifecycle")

    has_identity = set(AccountIdentity.objects.values_list("user_id", flat=True))
    has_lifecycle = set(AccountLifecycle.objects.values_list("user_id", flat=True))

    fixed_identity = fixed_lifecycle = 0
    for profile in Profile.objects.all().iterator():
        uid = profile.user_id
        if uid not in has_identity:
            AccountIdentity.objects.update_or_create(
                user_id=uid,
                defaults={
                    "real_name": getattr(profile, "real_name", "") or "",
                    "identity": getattr(profile, "identity", "") or "",
                    "pending_card_no": getattr(profile, "card_no", "") or "",
                },
            )
            fixed_identity += 1
        if uid not in has_lifecycle:
            AccountLifecycle.objects.update_or_create(
                user_id=uid,
                defaults={
                    "registration_deadline": getattr(profile, "registration_deadline", None),
                    "expiry_disabled_at": getattr(profile, "expiry_disabled_at", None),
                    "deleted_at": getattr(profile, "deleted_at", None),
                    "validity_notice_ack": getattr(profile, "validity_notice_ack", "") or "",
                    "must_change_password": bool(getattr(profile, "must_change_password", False)),
                },
            )
            fixed_lifecycle += 1

    if fixed_identity or fixed_lifecycle:
        print(
            f"[accounts.0035] 删列前补齐：identity {fixed_identity} 行 / "
            f"lifecycle {fixed_lifecycle} 行"
        )


def restore_from_split(apps, schema_editor):
    """反向：把新表数据搬回旧列。只用于回滚，正常路径不会走到。"""
    Profile = apps.get_model("accounts", "Profile")
    AccountIdentity = apps.get_model("accounts", "AccountIdentity")
    AccountLifecycle = apps.get_model("accounts", "AccountLifecycle")

    restored = 0
    for ident in AccountIdentity.objects.all().iterator():
        fields = {old: getattr(ident, new) for old, new in IDENTITY_MAP}
        restored += Profile.objects.filter(user_id=ident.user_id).update(**fields)
    for life in AccountLifecycle.objects.all().iterator():
        fields = {old: getattr(life, new) for old, new in LIFECYCLE_MAP}
        Profile.objects.filter(user_id=life.user_id).update(**fields)

    if restored:
        print(f"[accounts.0035] 回滚：{restored} 行已搬回旧列")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0034_accountidentity_accountlifecycle"),
    ]

    operations = [
        # 必须排在 RemoveField 之前：正向是「补齐」，反向是「搬回」
        migrations.RunPython(ensure_split_complete, restore_from_split),
        migrations.RemoveField(model_name="profile", name="card_no"),
        migrations.RemoveField(model_name="profile", name="deleted_at"),
        migrations.RemoveField(model_name="profile", name="expiry_disabled_at"),
        migrations.RemoveField(model_name="profile", name="identity"),
        migrations.RemoveField(model_name="profile", name="must_change_password"),
        migrations.RemoveField(model_name="profile", name="real_name"),
        migrations.RemoveField(model_name="profile", name="registration_deadline"),
        migrations.RemoveField(model_name="profile", name="validity_notice_ack"),
    ]
