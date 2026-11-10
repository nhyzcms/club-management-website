from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tutorials", "0002_seed_tags"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tutorial",
            name="tags",
        ),
        migrations.DeleteModel(
            name="TutorialTag",
        ),
    ]
