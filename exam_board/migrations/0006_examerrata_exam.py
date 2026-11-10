from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def attach_errata_to_latest_exam(apps, schema_editor):
    Exam = apps.get_model("exam_board", "Exam")
    ExamErrata = apps.get_model("exam_board", "ExamErrata")
    latest = Exam.objects.order_by("-id").first()
    if latest is None:
        return
    ExamErrata.objects.filter(exam_id__isnull=True).update(exam_id=latest.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("exam_board", "0005_examerrata_expires_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="examerrata",
            name="exam",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="errata",
                to="exam_board.exam",
                verbose_name="考试",
            ),
        ),
        migrations.RunPython(attach_errata_to_latest_exam, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="examerrata",
            options={"ordering": ["id"], "verbose_name": "题目误刊", "verbose_name_plural": "题目误刊"},
        ),
    ]
