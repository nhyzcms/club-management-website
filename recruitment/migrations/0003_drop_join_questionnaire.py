from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0002_seed"),
        ("activities", "0013_questionnaire"),
    ]

    operations = [
        migrations.DeleteModel(
            name="JoinResponse",
        ),
        migrations.DeleteModel(
            name="JoinQuestionnaire",
        ),
    ]
