"""授予「社长」组 accounts.can_review_identity（人工通道审核）。

SPA 身份审核不要求 is_staff；不授此权则仅超管能看到身份队列。
与 reviews/0003_grant_moderate_to_president 同模式。
"""
from django.db import migrations


def grant(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes
    from django.apps import apps as real_apps

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)

    group, _ = Group.objects.get_or_create(name="社长")
    perm = Permission.objects.get(
        content_type__app_label="accounts", codename="can_review_identity",
    )
    group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_alter_profile_identity"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
