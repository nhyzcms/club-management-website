"""权限规范化：给持有旧 CRUD 权限的组补上新语义权限。

应用代码（能力投影 / 序列化器 / 权限类）改用语义化工作流权限；
``add`` / ``view`` / ``change`` / ``delete`` 四种 Django 默认权限仅留给
admin 的 model 管理。本迁移按「持有旧权限的组 → 补新权限」通用映射，
保证升级后各组能力不变。
"""
from django.db import migrations

# 旧权限（组可能持有）→ 新语义权限（应用代码使用）
MAPPING = [
    ("news", "add_news", "manage_news"),
    ("news", "change_news", "manage_news"),
    ("activities", "change_activity", "manage_activity"),
    ("reviews", "view_feedback", "read_feedback"),
    ("about", "change_aboutpage", "manage_aboutpage"),
    ("exam_board", "add_exam", "manage_exams"),
    ("tutorials", "change_tutorial", "manage_tutorials"),
]


def grant(apps, schema_editor):
    from django.apps import apps as real_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)
    for app_label, old_code, new_code in MAPPING:
        old = Permission.objects.filter(
            content_type__app_label=app_label, codename=old_code,
        ).first()
        new = Permission.objects.filter(
            content_type__app_label=app_label, codename=new_code,
        ).first()
        if old is None or new is None:
            continue
        for group in Group.objects.filter(permissions=old).distinct():
            group.permissions.add(new)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_profile_email_notify_comment_and_more"),
        ("news", "0004_alter_news_options"),
        ("activities", "0014_alter_activity_options"),
        ("reviews", "0009_alter_feedback_options_and_more"),
        ("about", "0006_alter_aboutpage_options_alter_aboutblock_document"),
        ("exam_board", "0007_alter_exam_options"),
        ("tutorials", "0004_alter_tutorial_options_alter_tutorial_cover_and_more"),
    ]

    operations = [
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
