# 明信片 AI 配置新增「前置提示词」多行文本；无数据迁移（默认空 = 不附加）。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0006_postcard_ai_model_id_verbose'),
    ]

    operations = [
        migrations.AddField(
            model_name='postcardaiconfig',
            name='prompt_prefix',
            field=models.TextField(blank=True, default='', verbose_name='前置提示词'),
        ),
    ]
