"""把旧 Profile 邮件偏好（email_notify_*）迁移为通知订阅行。"""
from django.db import migrations

MAPPING = [
    ("email_notify_comment", "comment"),
    ("email_notify_review", "review"),
    ("email_notify_discipline", "discipline"),
]


def forward(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Subscription = apps.get_model("messaging", "NotificationSubscription")
    for field, source_key in MAPPING:
        rows = Profile.objects.filter(**{field: True}).values_list("user_id", flat=True)
        for user_id in rows.iterator():
            Subscription.objects.get_or_create(
                user_id=user_id,
                source_key=source_key,
                channel_key="email",
                defaults={"enabled": True},
            )


def backward(apps, schema_editor):
    Subscription = apps.get_model("messaging", "NotificationSubscription")
    for _, source_key in MAPPING:
        Subscription.objects.filter(source_key=source_key, channel_key="email").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0005_alter_notification_category_notificationdelivery_and_more"),
        ("accounts", "0008_profile_email_notify_comment_and_more"),
    ]

    operations = [migrations.RunPython(forward, backward)]
