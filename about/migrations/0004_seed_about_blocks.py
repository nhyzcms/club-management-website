from django.db import migrations

DEFAULT_BLOCKS = [
    ("club", "关于社团", 1),
    ("school", "关于一中", 2),
    ("site", "关于网站", 3),
    ("contact", "联系我们", 4),
    ("campus-overview", "校园一览", 5),
]


def seed_blocks(apps, schema_editor):
    AboutPage = apps.get_model("about", "AboutPage")
    AboutBlock = apps.get_model("about", "AboutBlock")
    page = AboutPage.objects.filter(pk=1).first()
    legacy_title = page.title if page else "关于社团"
    legacy_content = page.content if page else ""

    for key, title, order in DEFAULT_BLOCKS:
        defaults = {"title": title, "order": order, "content": ""}
        if key == "club":
            defaults["title"] = legacy_title or title
            defaults["content"] = legacy_content
        AboutBlock.objects.get_or_create(key=key, defaults=defaults)


def unseed_blocks(apps, schema_editor):
    AboutBlock = apps.get_model("about", "AboutBlock")
    AboutBlock.objects.filter(key__in=[k for k, _, _ in DEFAULT_BLOCKS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("about", "0003_aboutblock_and_overview"),
    ]

    operations = [
        migrations.RunPython(seed_blocks, reverse_code=unseed_blocks),
    ]
