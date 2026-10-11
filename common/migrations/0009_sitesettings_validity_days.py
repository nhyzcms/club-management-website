import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0008_sitesettings_authcode_redeem_per_user_per_hour"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="verification_valid_days",
            field=models.PositiveIntegerField(
                default=365,
                help_text="认证码 / 人工核验 / 邮箱验证通过后，认证状态的有效天数；过期需重新认证。",
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="认证有效期（天）",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="admin_valid_days",
            field=models.PositiveIntegerField(
                default=730,
                help_text="管理员身份自授予之日起的有效天数；过期需重新授予。超级管理员不受限。",
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="管理员身份有效期（天）",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="registration_verify_days",
            field=models.PositiveIntegerField(
                default=60,
                help_text="注册后未完成验证的宽限天数；超期将停用该账号。",
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="注册后验证宽限（天）",
            ),
        ),
    ]
