"""把旧的 messaging.mute_user 授权复制到 reviews.mute_user（跨 app 权限归位）。"""
from django.db import migrations


def forward(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct, _ = ContentType.objects.get_or_create(app_label="reviews", model="usermute")
    new_perm, _ = Permission.objects.get_or_create(
        content_type=ct, codename="mute_user", defaults={"name": "全站禁言"},
    )
    old_perm = Permission.objects.filter(
        content_type__app_label="messaging", codename="mute_user",
    ).first()
    if old_perm is None:
        return
    for uid in list(old_perm.user_set.values_list("pk", flat=True)):
        new_perm.user_set.add(uid)
    for gid in list(old_perm.group_set.values_list("pk", flat=True)):
        new_perm.group_set.add(gid)


def backward(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    new_perm = Permission.objects.filter(
        content_type__app_label="reviews", codename="mute_user",
    ).first()
    if new_perm is None:
        return
    new_perm.user_set.clear()
    new_perm.group_set.clear()


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0010_usermute_and_more"),
    ]

    operations = [migrations.RunPython(forward, backward)]
