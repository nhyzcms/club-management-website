
#需要上传收款码（支付宝/微信商家（个人也行）收款），这是注释
from django.db import migrations


def seed_support_block(apps, schema_editor):
    AboutBlock = apps.get_model("about", "AboutBlock")
    AboutBlock.objects.get_or_create(
        key="support-us",
        defaults={"title": "支持我们", "order": 6, "content": ""},
    )


def unseed_support_block(apps, schema_editor):
    AboutBlock = apps.get_model("about", "AboutBlock")
    AboutBlock.objects.filter(key="support-us").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("about", "0007_alter_aboutblock_document"),
    ]

    operations = [
        migrations.RunPython(seed_support_block, reverse_code=unseed_support_block),
    ]
