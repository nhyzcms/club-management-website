"""身份有效期提醒台账：``ValidityNotice``。

到期前两个月 / 一个月各发一次站内提醒（见 ``accounts.validity_notices``）需要幂等落账，
唯一键含 ``expires_at`` 快照，续期 / 重新委任后重新起算。
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_account_validity"),
    ]

    operations = [
        migrations.CreateModel(
            name="ValidityNotice",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
                    ),
                ),
                ("expires_at", models.DateTimeField(verbose_name="到期时间快照")),
                (
                    "level",
                    models.CharField(
                        choices=[("60d", "还剩两个月"), ("30d", "还剩一个月")],
                        max_length=8,
                        verbose_name="档位",
                    ),
                ),
                ("sent_at", models.DateTimeField(auto_now_add=True, verbose_name="发送时间")),
                (
                    "verification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="validity_notices",
                        to="accounts.verification",
                        verbose_name="验证通道",
                    ),
                ),
            ],
            options={
                "verbose_name": "身份有效期提醒",
                "verbose_name_plural": "身份有效期提醒",
                "ordering": ["-sent_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="validitynotice",
            constraint=models.UniqueConstraint(
                fields=("verification", "expires_at", "level"),
                name="unique_validity_notice_per_expiry_level",
            ),
        ),
    ]
