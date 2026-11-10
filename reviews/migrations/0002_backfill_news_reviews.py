"""存量新闻补审核记录：已发布视为通过，草稿视为待审。活动接入见 T11。"""
from django.db import migrations


def backfill(apps, schema_editor):
    News = apps.get_model("news", "News")
    Review = apps.get_model("reviews", "Review")
    for news in News.objects.all().iterator():
        Review.objects.get_or_create(
            news_id=news.pk,
            defaults={
                "status": "approved" if news.is_published else "pending",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0001_initial"),
        ("news", "0002_create_info_group"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
