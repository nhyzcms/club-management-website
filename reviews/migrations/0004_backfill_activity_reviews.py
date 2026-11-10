"""存量活动补审核记录：一律视为已通过（T11 接入前无审核门控）。"""
from django.db import migrations


def backfill(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    Review = apps.get_model("reviews", "Review")
    for activity in Activity.objects.all().iterator():
        Review.objects.get_or_create(
            activity_id=activity.pk,
            defaults={"status": "approved"},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0003_grant_moderate_to_president"),
        ("activities", "0011_activity_voting_enabled"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
