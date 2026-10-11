"""通知聚合去重：``Notification.dedup_key`` + 「同键至多一条未读」唯一约束。

- ``dedup_key`` 为空 = 不聚合（保持历史行为：每条事件一条通知）。
- 约束只作用于未读行（``read_at IS NULL``）且键非空，故聚合上线前的存量未读通知
  （键为空）不受影响；被读掉之后新的同事项通知照常新建。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0007_remove_usermute_messaging_u_user_id_c1296f_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="dedup_key",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=200, verbose_name="聚合键",
            ),
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                condition=models.Q(read_at__isnull=True) & ~models.Q(dedup_key=""),
                fields=("recipient", "dedup_key"),
                name="notification_unread_dedup_unique",
            ),
        ),
    ]
