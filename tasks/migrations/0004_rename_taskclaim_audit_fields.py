"""审计字段统一命名（B2 第二批）。

``TaskClaimRequest`` 此前用 ``reviewed_by`` / ``reviewed_at``（这张表没有说明
文字列，所以只有两件）。

只做数据库级 ``RENAME COLUMN``，数据不动。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0003_delete_tag_alter_task_tags"),
    ]

    operations = [
        migrations.RenameField("taskclaimrequest", "reviewed_by", "moderated_by"),
        migrations.RenameField("taskclaimrequest", "reviewed_at", "moderated_at"),
    ]
