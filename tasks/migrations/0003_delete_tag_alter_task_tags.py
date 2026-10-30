"""删掉 tasks 侧的 Tag 状态（B7）—— state-only，物理表不动。

``DeleteModel`` 真跑会 DROP TABLE ``tasks_tag``——而 common.Tag 还在用它。
``AlterField`` 改的是 M2M 指向（``tasks.Tag`` → ``common.Tag``），物理中间表
``tasks_task_tags`` 与 ``tasks_tag`` 都不变。两条都包 state-only。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0014_tag'),
        ('news', '0008_alter_news_tags'),
        ('tasks', '0002_delete_attachment'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name='Tag',
                ),
                migrations.AlterField(
                    model_name='task',
                    name='tags',
                    field=models.ManyToManyField(blank=True, related_name='tasks', to='common.tag', verbose_name='标签'),
                ),
            ],
            database_operations=[],
        ),
    ]
