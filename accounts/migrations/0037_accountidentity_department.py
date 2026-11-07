# 教师部门（2026-11-07）：``AccountIdentity`` 加 ``department`` 选填列。
# 目前仅教师身份登记（德育处 moral / 体育组 sports），其余身份恒为空串；
# 存量行由 default="" 兜底，无需数据回填。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0036_link_session_to_device"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountidentity",
            name="department",
            field=models.CharField(
                blank=True,
                choices=[("moral", "德育处"), ("sports", "体育组")],
                default="",
                max_length=20,
                verbose_name="所属部门",
            ),
        ),
    ]
