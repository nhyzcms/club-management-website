"""Notification.category 可选值增加 ``validity``（身份有效期提醒）。

choices 仅影响校验 / 展示（不建约束），但必须与模型同步记录，否则 ``makemigrations``
会持续探测到差异。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0008_notification_dedup_key"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="category",
            field=models.CharField(
                choices=[
                    ("review", "审核"),
                    ("activity", "活动"),
                    ("comment", "评论"),
                    ("dm", "私信"),
                    ("announcement", "广播"),
                    ("validity", "身份有效期"),
                    ("discipline", "纪律"),
                ],
                max_length=20,
                verbose_name="类别",
            ),
        ),
    ]
