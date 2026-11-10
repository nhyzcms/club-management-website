from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0004_backfill_activity_reviews"),
        ("tutorials", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="tutorial",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="review",
                to="tutorials.tutorial",
                verbose_name="教程",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="review",
            name="review_exactly_one_parent",
        ),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(news__isnull=False, activity__isnull=True, tutorial__isnull=True)
                    | models.Q(news__isnull=True, activity__isnull=False, tutorial__isnull=True)
                    | models.Q(news__isnull=True, activity__isnull=True, tutorial__isnull=False)
                ),
                name="review_exactly_one_parent",
            ),
        ),
    ]
