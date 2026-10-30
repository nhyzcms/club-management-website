"""审计字段统一命名（B2）。

同一组概念（谁处理的 / 什么时候 / 写了什么说明）此前有五个名字：
``reviewer`` / ``reviewed_by`` / ``closed_by`` / ``resolved_by`` / ``verified_by``。
审核台要做通用展示就得对每张表写一遍映射。

本迁移只做数据库级 ``RENAME COLUMN``——数据一行不动，可原地回滚。

**范围**：只覆盖 ``reviews`` 的三张表。其余三处（``Submission`` /
``PasswordResetRequest`` / ``TaskClaimRequest``）另开一批；``accounts.Verification``
的 ``verified_by/at`` 是「认证通过」不是「审核」，语义不同，不参与统一。

**对外契约**：serializer 用 ``source=`` 映射回旧名字（``comment`` / ``reviewer`` /
``closed_by`` / ``resolved_by`` …），前端与 API 零变化。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0012_reportcase_target_review_target"),
    ]

    operations = [
        # Review：reviewer / reviewed_at / comment
        migrations.RenameField("review", "comment", "moderation_note"),
        migrations.RenameField("review", "reviewer", "moderated_by"),
        migrations.RenameField("review", "reviewed_at", "moderated_at"),
        # Feedback：closed_by / closed_at / close_note
        migrations.RenameField("feedback", "closed_by", "moderated_by"),
        migrations.RenameField("feedback", "closed_at", "moderated_at"),
        migrations.RenameField("feedback", "close_note", "moderation_note"),
        # ReportCase：resolved_by / resolved_at / resolution_comment
        migrations.RenameField("reportcase", "resolved_by", "moderated_by"),
        migrations.RenameField("reportcase", "resolved_at", "moderated_at"),
        migrations.RenameField("reportcase", "resolution_comment", "moderation_note"),
    ]
