"""授予「社长」「信息组」密码重置审批权限（2026-10）。

忘记密码 → 管理员手动重置：审批入口在审核台「密码重置」桌（/#/reviews、/#/m/review）。
权限代号 ``accounts.review_password_reset``（建在 PasswordResetRequest.Meta.permissions）。
与 0006（身份审核）/ 0016（名册）同模式；不授则仅超管可见。
"""
from django.db import migrations

GROUPS = ["社长", "信息组"]
CODENAMES = [
    ("accounts", "review_password_reset"),
]


def grant(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes
    from django.apps import apps as real_apps

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # 新模型的 permissions 由 post_migrate 的 create_permissions 生成；
    # 本迁移在数据迁移阶段就跑授权，故先显式补齐（与 0013/0016 同做法）。
    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)

    for group_name in GROUPS:
        group, _ = Group.objects.get_or_create(name=group_name)
        for app_label, codename in CODENAMES:
            perm = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename,
            ).first()
            if perm is not None:
                group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0025_password_reset_request"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
