from django.db import migrations

from recruitment.models import default_schema


def seed(apps, schema_editor):
    RecruitmentNotice = apps.get_model("recruitment", "RecruitmentNotice")
    JoinQuestionnaire = apps.get_model("recruitment", "JoinQuestionnaire")
    RecruitmentNotice.objects.get_or_create(
        pk=1,
        defaults={"content": "<p>欢迎加入南汇一中传媒社。请认真阅读本公告后再填写自我介绍问卷。</p>"},
    )
    JoinQuestionnaire.objects.get_or_create(pk=1, defaults={"schema": default_schema()})


def unseed(apps, schema_editor):
    apps.get_model("recruitment", "RecruitmentNotice").objects.filter(pk=1).delete()
    apps.get_model("recruitment", "JoinQuestionnaire").objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
