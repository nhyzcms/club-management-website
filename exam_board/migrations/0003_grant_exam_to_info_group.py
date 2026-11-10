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

    group, _ = Group.objects.get_or_create(name="信息组")
    for codename in ("add_examdata", "change_examdata", "delete_examdata"):
        perm = Permission.objects.get(content_type__app_label="exam_board", codename=codename)
        group.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("exam_board", "0002_harden_examdata"),
        ("accounts", "0002_seed_default_groups"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
