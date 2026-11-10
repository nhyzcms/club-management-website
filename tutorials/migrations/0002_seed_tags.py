from django.db import migrations

TAGS = [
    ("Ps", "tool", 1),
    ("Ae", "tool", 2),
    ("Pr", "tool", 3),
    ("剪映", "tool", 4),
    ("入门", "scene", 1),
    ("进阶", "scene", 2),
    ("比赛", "scene", 3),
    ("宣传", "scene", 4),
]


def seed(apps, schema_editor):
    TutorialTag = apps.get_model("tutorials", "TutorialTag")
    for name, kind, order in TAGS:
        TutorialTag.objects.get_or_create(name=name, defaults={"kind": kind, "order": order})


def unseed(apps, schema_editor):
    TutorialTag = apps.get_model("tutorials", "TutorialTag")
    TutorialTag.objects.filter(name__in=[n for n, _, _ in TAGS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tutorials", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
