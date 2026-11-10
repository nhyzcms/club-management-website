from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0002_create_info_group"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="news",
            name="category",
        ),
    ]
