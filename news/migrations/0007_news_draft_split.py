"""把 News 上的草稿列拆到独立的 NewsDraft 表（B7）。

**顺序是关键。** Django 自动生成的是「先删列、后建表」——那样草稿全丢。
这里改成「建表 → 搬数据 → 删列」，并在回滚路径上把草稿写回主表。

生产实测（2026-10-30）：迁移前 10 条新闻的 ``draft_*`` 全部为空
（``draft_saved_at`` 为 NULL、三个文本列长度为 0），所以本次实际搬运 0 行。
逻辑仍然写全，因为测试环境和未来数据不该被这个顺序问题坑掉。
"""
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def copy_drafts_to_table(apps, schema_editor):
    """把主表上的草稿搬到 NewsDraft。

    三种形态都要处理：
    - 有内容 + 有保存时间（正常草稿）→ 原样搬；
    - 有内容 + 无保存时间（历史脏数据）→ 用 ``updated_at`` 兜底，别丢内容；
    - 无内容 + 无时间（空占位，绝大多数）→ 跳过，不留空行。
    """
    News = apps.get_model("news", "News")
    NewsDraft = apps.get_model("news", "NewsDraft")
    rows = News.objects.all().values(
        "pk", "draft_title", "draft_summary", "draft_content",
        "draft_saved_at", "updated_at",
    )
    moved = 0
    for row in rows.iterator():
        has_content = bool(
            row["draft_title"] or row["draft_summary"] or row["draft_content"]
        )
        if not has_content and row["draft_saved_at"] is None:
            continue
        NewsDraft.objects.create(
            news_id=row["pk"],
            title=row["draft_title"] or "",
            summary=row["draft_summary"] or "",
            content=row["draft_content"] or "",
            saved_at=row["draft_saved_at"] or row["updated_at"],
        )
        moved += 1
    # 部署日志里要看得见「搬了几行」——生产实测 0 行，若哪天不是 0，日志能立刻发现。
    print(f"[news.0007] 草稿搬到 NewsDraft：{moved} 行")


def copy_drafts_back_to_news(apps, schema_editor):
    """回滚：草稿写回主表列。

    执行时机由 Django 保证——反向跑时 ``RemoveField`` 的反向操作（AddField）
    已经先把列建回来了，本函数才被调用，之后才轮到删 NewsDraft 表。
    """
    News = apps.get_model("news", "News")
    NewsDraft = apps.get_model("news", "NewsDraft")
    for draft in NewsDraft.objects.all().iterator():
        News.objects.filter(pk=draft.news_id).update(
            draft_title=draft.title,
            draft_summary=draft.summary,
            draft_content=draft.content,
            draft_saved_at=draft.saved_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0006_news_draft_content_news_draft_saved_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="NewsDraft",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(blank=True, default="", max_length=200, verbose_name="标题")),
                ("summary", models.CharField(blank=True, default="", max_length=280, verbose_name="摘要")),
                ("content", models.TextField(blank=True, default="", verbose_name="正文（HTML）")),
                ("saved_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="保存时间")),
                (
                    "news",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="draft_record",
                        to="news.news",
                        verbose_name="新闻",
                    ),
                ),
            ],
            options={
                "verbose_name": "新闻草稿",
                "verbose_name_plural": "新闻草稿",
                "ordering": ["-saved_at"],
            },
        ),
        # 必须先搬再删。
        migrations.RunPython(copy_drafts_to_table, copy_drafts_back_to_news),
        migrations.RemoveField(model_name="news", name="draft_content"),
        migrations.RemoveField(model_name="news", name="draft_saved_at"),
        migrations.RemoveField(model_name="news", name="draft_summary"),
        migrations.RemoveField(model_name="news", name="draft_title"),
    ]
