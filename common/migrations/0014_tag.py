"""把 Tag 从 tasks 移到 common（B7）—— 状态搬运，零 DDL。

物理表 ``tasks_tag`` 原地不动：新模型 ``Meta.db_table`` 写死了同名。
真跑 ``CreateModel`` 会 ``CREATE TABLE tasks_tag`` 撞已有表，所以整条操作
包进 ``SeparateDatabaseAndState`` + ``database_operations=[]``。

配套：``tasks/0003`` 用 state-only 删掉旧模型状态；``common/0015`` 把
``manage_tags`` 的既有授权从 ``tasks`` 复制到 ``common``。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0013_sitesettings_member_lookup_per_ip_per_hour'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Tag',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=50, unique=True, verbose_name='名称')),
                        ('color', models.CharField(default='#007bff', max_length=7, verbose_name='颜色')),
                    ],
                    options={
                        'verbose_name': '标签',
                        'verbose_name_plural': '标签',
                        'db_table': 'tasks_tag',
                        'ordering': ['name'],
                        'permissions': [('manage_tags', '可管理标签')],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
