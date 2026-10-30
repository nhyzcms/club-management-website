"""审计字段统一命名（B2 第二批）。

``Submission`` 此前用 ``review_comment`` / ``reviewed_by`` / ``reviewed_at``——
和 ``Review``（``comment``）、``Feedback``（``close_note``）、``ReportCase``
（``resolution_comment``）各有一套名字，审核台要通用展示就得写五套映射。

只做数据库级 ``RENAME COLUMN``，数据不动。

**不在本迁移**：``review_status`` 保留原名。它是状态列不是审计三件套——
「谁审的 / 什么时候 / 写了什么」才有统一价值，状态机每个 app 本来就不一样。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0018_questionnaireresponse_schema_snapshot_and_more"),
    ]

    operations = [
        migrations.RenameField("submission", "review_comment", "moderation_note"),
        migrations.RenameField("submission", "reviewed_by", "moderated_by"),
        migrations.RenameField("submission", "reviewed_at", "moderated_at"),
    ]
