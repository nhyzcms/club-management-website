"""授予「社长」「信息组」社员名册管理权限（ADR-0025）。

名册模块整体由命名工作流权限 ``accounts.manage_member_roster`` 收口：
导入 / 导出二维码 / 自动重匹配 / 手动绑定解绑 / 后台列表与编辑（admin 直查同权）。
与 accounts/0012（认证码）、0006（审核）同模式；不授则仅超管可见。
"""
from django.db import migrations

GROUPS = ["社长", "信息组"]
CODENAMES = [
    ("accounts", "manage_member_roster"),
]


def grant(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes
    from django.apps import apps as real_apps

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # 先确保所有 app 的 ContentType 与 Permission 已生成（含新模型的四个默认权限）
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
        ("accounts", "0015_identityimportbatch_memberidentity"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
