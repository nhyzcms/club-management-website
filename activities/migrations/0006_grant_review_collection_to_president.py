"""授予「社长」组 activities.review_collection 权限（征集复审）。

与 accounts/0002_seed_default_groups 同模式：先确保 activities 的权限已生成，再把
review_collection 加到社长组。新增命名权限即按此落一组（ADR 0005：权限由组分配）。
"""
from django.db import migrations


def grant(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes
    from django.apps import apps as real_apps

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # 先确保所有 app 的 ContentType 与 Permission（含 Meta.permissions 自定义项）已生成
    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)

    group, _ = Group.objects.get_or_create(name="社长")
    perm = Permission.objects.get(
        content_type__app_label="activities", codename="review_collection",
    )
    group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0005_alter_activity_options"),
        ("accounts", "0002_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
