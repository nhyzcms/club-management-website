"""B9：删除 Attachment 的 5 个旧父级外键。

## 前向

约束先删、列后删。`target` 在 B1 就已回填完毕（`attachments/0007` 的
`backfill` + `TargetBackfillMixin` 的 save 钩子），所以这里没有数据要搬，
只是把「同一件事的两种表示」收敛成一种。

## 反向为什么要手写

`RemoveField` 的反向是 `AddField`——**加回来是空列**。而
`attachment_exactly_one_parent` 这个 CheckConstraint 要求「5 个旧列里恰好一个
非空」，空列会让它在任何存量行上直接失败。

所以这里在 `RemoveField` **之前**插了一个 `RunPython`：正向是空操作，反向在
列加回来之后按 `target` 把值填回去。放在前面是因为 Django 反向执行时按
operations 逆序走——放前面才会在 AddField 之后执行。
"""
from django.db import migrations, models

#: 旧列名 → ContentTarget.kind。两者同名，但显式写出来以免以后 kind 改名时静默错位。
LEGACY_FIELDS = ("task", "feedback", "news", "submission", "exhibit")


def backfill_from_target(apps, schema_editor):
    """反向：把 target 上的宿主写回 5 个旧列。"""
    Attachment = apps.get_model("attachments", "Attachment")
    for field in LEGACY_FIELDS:
        # values_list 一次取 (pk, object_id)，避免逐行 row.target 再查一次
        pairs = Attachment.objects.filter(target__kind=field).values_list(
            "pk", "target__object_id",
        )
        for pk, object_id in pairs.iterator():
            # 用 .update() 而不是 save()：此刻模型上 5 个旧列都在，但 save() 会
            # 触发一堆无关逻辑；这里只要写一列。
            Attachment.objects.filter(pk=pk).update(**{f"{field}_id": object_id})


def noop(apps, schema_editor):
    """正向：没有要搬的数据（B1 已回填）。"""


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0018_split_site_settings"),
        ("attachments", "0007_attachment_target"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="attachment",
            name="attachment_exactly_one_parent",
        ),
        # 反向回填必须排在 RemoveField 之前（见模块 docstring）
        migrations.RunPython(noop, backfill_from_target),
        migrations.RemoveField(model_name="attachment", name="exhibit"),
        migrations.RemoveField(model_name="attachment", name="feedback"),
        migrations.RemoveField(model_name="attachment", name="news"),
        migrations.RemoveField(model_name="attachment", name="submission"),
        migrations.RemoveField(model_name="attachment", name="task"),
    ]
