"""News.tags 改指向 ``common.Tag``（B7）—— state-only。

物理中间表 ``news_news_tags`` 与目标表 ``tasks_tag`` 都不变，只是 Django
状态里的指向变了。真跑 ``AlterField`` 在部分后端会重建中间表，没必要冒这个险。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0014_tag'),
        ('news', '0007_news_draft_split'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='news',
                    name='tags',
                    field=models.ManyToManyField(blank=True, related_name='news', to='common.tag', verbose_name='标签'),
                ),
            ],
            database_operations=[],
        ),
    ]
