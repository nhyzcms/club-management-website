"""B9：删除 CommentThread 的 3 个旧宿主外键。

## 前向

先删约束、再删列。`target` 在 `messaging/0010` 已回填，`thread_for()` 在双写期
也一直两个都写，所以没有数据要搬。

## 反向为什么要手写

`RemoveField` 的反向是 `AddField`——加回来是空列，而
`commentthread_exactly_one_parent` 要求「news / activity / task 里恰好一个非空」，
空列会让它在任何存量行上直接失败。

`RunPython` 放在 `RemoveField` **之前**：Django 反向执行按 operations 逆序走，
放前面才会在 AddField 之后跑，那时列已经回来了。
"""
from django.db import migrations

LEGACY_FIELDS = ("news", "activity", "task")


def backfill_from_target(apps, schema_editor):
    """反向：把 target 上的宿主写回 3 个旧列。"""
    CommentThread = apps.get_model("messaging", "CommentThread")
    for field in LEGACY_FIELDS:
        pairs = CommentThread.objects.filter(target__kind=field).values_list(
            "pk", "target__object_id",
        )
        for pk, object_id in pairs.iterator():
            CommentThread.objects.filter(pk=pk).update(**{f"{field}_id": object_id})


def noop(apps, schema_editor):
    """正向：没有要搬的数据（B1 已回填）。"""


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0018_split_site_settings"),
        ("messaging", "0010_commentthread_target"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="commentthread",
            name="commentthread_exactly_one_parent",
        ),
        migrations.RunPython(noop, backfill_from_target),
        migrations.RemoveField(model_name="commentthread", name="activity"),
        migrations.RemoveField(model_name="commentthread", name="news"),
        migrations.RemoveField(model_name="commentthread", name="task"),
    ]
