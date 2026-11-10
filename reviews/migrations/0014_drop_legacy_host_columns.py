"""B9：删除 Review 与 ReportCase 的旧宿主列。

## 前向

`Review` 删 3 个（news / activity / tutorial），`ReportCase` 删 4 个内容列
（news / activity / tutorial / comment）——**`reported_user` 保留**：「人」不是
「内容」，举报用户与举报内容是两种关系，可以同时存在，且用户删除后举报案要留档。

`target` 在 `reviews/0012` 已回填，双写期 `open_review()` / `file()` 也一直两个都写。

## 约束的替换

旧的两条 CheckConstraint（「恰好一个旧列非空」）和 4 条 UniqueConstraint
（每张内容表一个「同一对象只能有一个未结案」）都依赖被删的列，必须一起删。
换成按 `target` 的一条 `one_open_report_per_target`——`ContentTarget` 已经表达了
「这是哪条内容」，按内容类型分四条是同一个规则写四遍。

`one_open_report_per_user` 保留：它挂在 `reported_user` 上，和 target 无关。

## 反向为什么要手写

`RemoveField` 的反向是 `AddField`——加回来是空列。而两条 CheckConstraint 要求
「恰好一个非空」，空列会让它们在存量行上直接失败。

`RunPython` 放在所有 `RemoveField` **之前**：Django 反向按 operations 逆序执行，
放前面才会在 AddField 之后跑。
"""
from django.db import migrations, models

REVIEW_LEGACY = ("news", "activity", "tutorial")
REPORTCASE_LEGACY = ("news", "activity", "tutorial", "comment")


def backfill_from_target(apps, schema_editor):
    """反向：把 target 上的宿主写回旧列。"""
    Review = apps.get_model("reviews", "Review")
    for field in REVIEW_LEGACY:
        pairs = Review.objects.filter(target__kind=field).values_list(
            "pk", "target__object_id",
        )
        for pk, object_id in pairs.iterator():
            Review.objects.filter(pk=pk).update(**{f"{field}_id": object_id})

    ReportCase = apps.get_model("reviews", "ReportCase")
    for field in REPORTCASE_LEGACY:
        pairs = ReportCase.objects.filter(target__kind=field).values_list(
            "pk", "target__object_id",
        )
        for pk, object_id in pairs.iterator():
            ReportCase.objects.filter(pk=pk).update(**{f"{field}_id": object_id})


def noop(apps, schema_editor):
    """正向：没有要搬的数据（B1 已回填）。"""


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0018_split_site_settings"),
        ("reviews", "0013_rename_audit_fields"),
    ]

    operations = [
        # ── 旧约束先下（它们引用即将被删的列）──────────────────────────
        migrations.RemoveConstraint(
            model_name="reportcase", name="reportcase_exactly_one_target",
        ),
        migrations.RemoveConstraint(
            model_name="reportcase", name="one_open_report_per_news",
        ),
        migrations.RemoveConstraint(
            model_name="reportcase", name="one_open_report_per_activity",
        ),
        migrations.RemoveConstraint(
            model_name="reportcase", name="one_open_report_per_comment",
        ),
        migrations.RemoveConstraint(
            model_name="reportcase", name="one_open_report_per_tutorial",
        ),
        migrations.RemoveConstraint(
            model_name="review", name="review_exactly_one_parent",
        ),
        # ── 换成按 target 的一条 ────────────────────────────────────────
        migrations.AddConstraint(
            model_name="reportcase",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="open", target__isnull=False),
                fields=("target",),
                name="one_open_report_per_target",
            ),
        ),
        # ── 反向回填（必须排在 RemoveField 之前）───────────────────────
        migrations.RunPython(noop, backfill_from_target),
        # ── 删列 ────────────────────────────────────────────────────────
        migrations.RemoveField(model_name="reportcase", name="activity"),
        migrations.RemoveField(model_name="reportcase", name="comment"),
        migrations.RemoveField(model_name="reportcase", name="news"),
        migrations.RemoveField(model_name="reportcase", name="tutorial"),
        migrations.RemoveField(model_name="review", name="activity"),
        migrations.RemoveField(model_name="review", name="news"),
        migrations.RemoveField(model_name="review", name="tutorial"),
    ]
