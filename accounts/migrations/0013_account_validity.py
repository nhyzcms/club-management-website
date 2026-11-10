"""账号身份有效期（ADR-0041）：加有效期字段 + 存量回填 + 授予 manage_validity。

- ``Verification.expires_at``：通道认证有效期（认证通道 1 年、委任通道 2 年、超管永久）。
- ``Profile.registration_deadline`` / ``expiry_disabled_at``：注册宽限覆盖 / 超期停用标记。
- ``AuthCodeRedemption`` 唯一约束放宽为 (user, authcode)：认证过期后可重新兑换不同码。
- ``Verification`` Meta 增 ``manage_validity`` 自定义权限（AlterModelOptions 记录，供 post_migrate 的
  create_permissions 创建）。
- 回填：存量 approved 认证通道 = 迁移时刻 + 1 年；管理员委任 = 迁移时刻 + 2 年；超管 = 永久。
- 授予「社长」「信息组」accounts.manage_validity。
"""
from django.db import migrations, models
from django.utils import timezone

VERIFICATION_VALID_DAYS = 365
ADMIN_VALID_DAYS = 730


def backfill_validity(apps, schema_editor):
    from datetime import timedelta

    Verification = apps.get_model("accounts", "Verification")
    now = timezone.now()
    for v in Verification.objects.filter(
        channel__in=["email", "manual", "authcode"], status="approved",
    ):
        v.expires_at = now + timedelta(days=VERIFICATION_VALID_DAYS)
        v.save(update_fields=["expires_at"])
    for v in Verification.objects.filter(channel="appointment", status="approved"):
        v.expires_at = None if v.user.is_superuser else (now + timedelta(days=ADMIN_VALID_DAYS))
        v.save(update_fields=["expires_at"])


def grant_manage_validity(apps, schema_editor):
    from django.apps import apps as real_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # 先确保 accounts 的 ContentType 与 Permission 已生成（含 manage_validity）。
    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)

    perm = Permission.objects.filter(
        content_type__app_label="accounts", codename="manage_validity",
    ).first()
    if perm is None:
        return
    for group_name in ["社长", "信息组"]:
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_grant_authcode_perms"),
    ]

    operations = [
        migrations.AddField(
            model_name="verification",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="有效期至"),
        ),
        migrations.AddField(
            model_name="profile",
            name="registration_deadline",
            field=models.DateTimeField(blank=True, null=True, verbose_name="注册验证截止"),
        ),
        migrations.AddField(
            model_name="profile",
            name="expiry_disabled_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="因超期停用时间"),
        ),
        migrations.AlterModelOptions(
            name="verification",
            options={
                "ordering": ["user", "channel"],
                "permissions": [("manage_validity", "可以管理账号 / 认证有效期")],
                "verbose_name": "验证通道",
                "verbose_name_plural": "验证通道",
            },
        ),
        migrations.RemoveConstraint(
            model_name="authcoderedemption",
            name="unique_authcode_per_user",
        ),
        migrations.AddConstraint(
            model_name="authcoderedemption",
            constraint=models.UniqueConstraint(
                fields=("user", "authcode"), name="unique_authcode_per_user_code"
            ),
        ),
        migrations.RunPython(backfill_validity, migrations.RunPython.noop),
        migrations.RunPython(grant_manage_validity, migrations.RunPython.noop),
    ]
