"""审计字段统一命名（B2 第二批）。

``PasswordResetRequest`` 此前用 ``review_note`` / ``reviewed_by`` / ``reviewed_at``。

**有意不改** ``Verification.verified_by`` / ``verified_at``：那是「认证通过」，
不是「审核处理」。两者在业务上是不同的动作（认证有面签 / 材料核验，审核是
内容或申请的处理），为了命名整齐把领域概念合并，是这类重构最典型的错误。

只做数据库级 ``RENAME COLUMN``，数据不动。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0032_alter_usersession_device_id"),
    ]

    operations = [
        migrations.RenameField("passwordresetrequest", "reviewed_at", "moderated_at"),
        migrations.RenameField("passwordresetrequest", "reviewed_by", "moderated_by"),
        migrations.RenameField("passwordresetrequest", "review_note", "moderation_note"),
    ]
