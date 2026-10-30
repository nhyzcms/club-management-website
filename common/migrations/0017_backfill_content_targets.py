"""把 4 张多态表上的旧列回填成 ContentTarget 指针（B1）。

幂等：只处理 ``target`` 为空的行，重复跑不会重复建 ContentTarget。

放在一个集中迁移里而不是四份：逻辑完全一样（「按旧列找到 kind 与 object_id →
get_or_create target → 指过去」），分四份只会有四个地方需要同步改。
代价是本迁移依赖其他 app 的 AddField 迁移（见 dependencies）。
"""

from django.db import migrations

# (app_label, ModelName, {旧列名: kind})
# dict 保持声明顺序：合法数据里恰好只有一个旧列非空，取第一个命中即可。
BACKFILLS = [
    (
        "attachments", "Attachment",
        {
            "task_id": "task",
            "feedback_id": "feedback",
            "news_id": "news",
            "submission_id": "submission",
            "exhibit_id": "exhibit",
        },
    ),
    (
        "reviews", "Review",
        {"news_id": "news", "activity_id": "activity", "tutorial_id": "tutorial"},
    ),
    (
        "reviews", "ReportCase",
        {
            "news_id": "news",
            "activity_id": "activity",
            "tutorial_id": "tutorial",
            "comment_id": "comment",
        },
    ),
    (
        "messaging", "CommentThread",
        {"news_id": "news", "activity_id": "activity", "task_id": "task"},
    ),
]


def backfill(apps, schema_editor):  # noqa: ARG001
    ContentTarget = apps.get_model("common", "ContentTarget")
    grand_total = 0
    for app_label, model_name, mapping in BACKFILLS:
        Model = apps.get_model(app_label, model_name)
        moved = 0
        skipped = 0
        for row in Model.objects.filter(target__isnull=True).iterator():
            hit = None
            for field, kind in mapping.items():
                object_id = getattr(row, field)
                if object_id is not None:
                    hit = (kind, object_id)
                    break
            if hit is None:
                # 旧约束保证「恰好一个父级」，走到这里说明是绕过约束的历史脏数据。
                # 不猜、不造 target——留给 B9 的 prune 命令与人工核查。
                skipped += 1
                continue
            target, _ = ContentTarget.objects.get_or_create(kind=hit[0], object_id=hit[1])
            Model.objects.filter(pk=row.pk).update(target=target)
            moved += 1
        print(f"[common.0017] {model_name}: 回填 {moved} 行，无父级跳过 {skipped} 行")
        grand_total += moved
    print(f"[common.0017] 合计回填 {grand_total} 行")


def unbackfill(apps, schema_editor):  # noqa: ARG001
    """回滚：清掉指针。

    不删 ContentTarget：同一个 target 可能被附件、评论、审核、举报共用，
    清指针已经足以回到「双写前」的读取路径，删行反而会误伤。
    """
    for app_label, model_name, _mapping in BACKFILLS:
        Model = apps.get_model(app_label, model_name)
        Model.objects.update(target=None)


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0016_contenttarget"),
        ("attachments", "0007_attachment_target"),
        ("reviews", "0012_reportcase_target_review_target"),
        ("messaging", "0010_commentthread_target"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
