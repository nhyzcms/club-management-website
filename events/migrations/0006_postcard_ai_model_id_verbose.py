# 仅改 verbose_name（「模型名」→「模型 ID」），不动列；无数据迁移。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0005_postcard_ai_timeout_default'),
    ]

    operations = [
        migrations.AlterField(
            model_name='postcardaiconfig',
            name='model',
            field=models.CharField(blank=True, default='', max_length=128, verbose_name='模型 ID'),
        ),
    ]
