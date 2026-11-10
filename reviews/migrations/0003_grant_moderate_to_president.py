"""授予「社长」组 reviews.moderate（统一审核）。免审发布不默认发给信息组。"""
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
        content_type__app_label="reviews", codename="moderate",
    )
    group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0002_backfill_news_reviews"),
        ("accounts", "0002_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
