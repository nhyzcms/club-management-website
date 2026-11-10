"""Seed default groups.

History rewrite (2026-08): dropped the ``proposals`` permission grants and the
dependency on ``proposals.0001``. Already-applied databases never re-run this
file; new installs get task perms here and ``reviews.view_feedback`` /
``handle_report`` from the reviews 0007–0008 squash.
"""
from django.db import migrations


def seed(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes
    from django.apps import apps as real_apps

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # 先确保所有 app 的 ContentType 与 Permission（含模型 Meta.permissions 自定义项）已生成
    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)

    GROUP_PERMISSIONS = {
        "信息组": [
            ("news", "add_news"),
            ("news", "change_news"),
            ("news", "delete_news"),
        ],
        "社长": [
            ("tasks", "manage_tasks"),
            ("tasks", "assign_task"),
            ("tasks", "manage_tags"),
        ],
    }

    for group_name, codenames in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        for app_label, codename in codenames:
            perm = Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
            group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("news", "0002_create_info_group"),
        ("tasks", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
