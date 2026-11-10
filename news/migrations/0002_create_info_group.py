from django.db import migrations

INFO_GROUP_NAME = "信息组"


def create_info_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=INFO_GROUP_NAME)


def remove_info_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=INFO_GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_info_group, reverse_code=remove_info_group),
    ]
