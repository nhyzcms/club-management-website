"""把 ``manage_tags`` 的既有授权从 tasks 复制到 common（B7）。

Tag 的 app_label 从 ``tasks`` 变成 ``common``，权限 codename 随之变成
``common.manage_tags``。Django 只会为新模型建一条**新的、没人持有的**权限行，
**不会**搬运旧授权——不复制的话，原本能管标签的组会突然失去权限，
症状是「标签页能看、一保存就 403」。

生产影响面（2026-10-30 实测）：2 个组持有该权限、0 个用户直授。
旧权限行保留不删（不再被读取，留着便于回滚与追溯）。
"""
from django.db import migrations


def _permission_pair(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    old_ct = ContentType.objects.filter(app_label="tasks", model="tag").first()
    # 迁移期间 post_migrate 还没跑，ContentType 可能尚不存在 → 就地建。
    # 注意：Django 2.0 起 ContentType 没有 name 字段（已改为 property），别传。
    new_ct, _ = ContentType.objects.get_or_create(app_label="common", model="tag")
    if old_ct is None:
        return None, None
    old_perm = Permission.objects.filter(
        content_type=old_ct, codename="manage_tags",
    ).first()
    if old_perm is None:
        return None, None
    new_perm, _ = Permission.objects.get_or_create(
        content_type=new_ct, codename="manage_tags", defaults={"name": "可管理标签"},
    )
    return old_perm, new_perm


def copy_grants(apps, schema_editor):
    old_perm, new_perm = _permission_pair(apps)
    if old_perm is None or new_perm is None:
        return
    for uid in old_perm.user_set.values_list("pk", flat=True):
        new_perm.user_set.add(uid)
    for gid in old_perm.group_set.values_list("pk", flat=True):
        new_perm.group_set.add(gid)


def drop_grants(apps, schema_editor):
    """回滚：撤掉复制到 common 的授权。旧行本来就没动，无需恢复。"""
    _, new_perm = _permission_pair(apps)
    if new_perm is None:
        return
    new_perm.user_set.clear()
    new_perm.group_set.clear()


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0014_tag"),
    ]

    operations = [
        migrations.RunPython(copy_grants, drop_grants),
    ]
