"""授予「社长」「信息组」全站弹窗公告管理权限（ADR-0042）。

与 accounts/0012（认证码）、0016（社员名册）同模式：模块整体由命名工作流权限
``announcements.manage_announcements`` 收口——后台列表 / 新增 / 编辑 / 已读明细
全部看这一个权限（``AnnouncementAdmin`` 覆写了 has_*_permission），不授则仅超管可用。
"""
from django.db import migrations

GROUPS = ["社长", "信息组"]
CODENAMES = [
    ("announcements", "manage_announcements"),
]


def grant(apps, schema_editor):
    from django.apps import apps as real_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # 先确保所有 app 的 ContentType 与 Permission 已生成（含新模型的自定义权限）
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
        ("announcements", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
