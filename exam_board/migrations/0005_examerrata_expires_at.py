from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exam_board", "0004_exam_batch_subject_errata"),
    ]

    operations = [
        migrations.AddField(
            model_name="examerrata",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="到期（本场结束）"),
        ),
    ]
