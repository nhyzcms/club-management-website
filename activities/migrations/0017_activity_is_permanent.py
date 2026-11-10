from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0016_remove_questionnaireresponse_unique_questionnaire_response_per_user_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="is_permanent",
            field=models.BooleanField(default=False, verbose_name="长期有效（不设截止）"),
        ),
    ]
