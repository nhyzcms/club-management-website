from django.db import migrations


def seed_about_page(apps, schema_editor):
    """种子：保证「关于」页单例在 migrate 后立即可用（默认标题，正文留待站长首填）。"""
    AboutPage = apps.get_model("about", "AboutPage")
    AboutPage.objects.get_or_create(
        pk=1, defaults={"title": "关于我们", "content": ""},
    )


def remove_about_page(apps, schema_editor):
    AboutPage = apps.get_model("about", "AboutPage")
    AboutPage.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("about", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_about_page, reverse_code=remove_about_page),
    ]
