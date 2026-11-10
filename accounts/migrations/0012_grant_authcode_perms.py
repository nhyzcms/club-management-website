"""授予「社长」「信息组」认证码 CRUD 权限（ADR-0020，后台生成侧）。

认证码由后台直接创造：生成 / 查看 / 吊销 / 删除需要 accounts.add_authcode /
view_authcode / change_authcode / delete_authcode 四个 Django 默认权限（admin 专用
词汇；与语义化工作流权限体系并存，见 0009 注释）。后台操作需 is_staff；不授此权则
仅超管能进后台管理认证码。
与 accounts/0006_grant_review_identity_to_president 同模式。
"""
from django.db import migrations

GROUPS = ["社长", "信息组"]
CODENAMES = [
    ("accounts", "add_authcode"),
    ("accounts", "view_authcode"),
    ("accounts", "change_authcode"),
    ("accounts", "delete_authcode"),
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
        ("accounts", "0011_authcode_channel"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
