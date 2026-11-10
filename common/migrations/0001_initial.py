from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SiteSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "verification_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="关闭后不可新开或完成任何验证通道；已通过者仍算已验证。",
                        verbose_name="验证通道开启",
                    ),
                ),
                (
                    "registration_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="关闭后自助注册接口返回 403。",
                        verbose_name="开放自助注册",
                    ),
                ),
                (
                    "register_per_ip_per_day",
                    models.PositiveIntegerField(
                        default=5, verbose_name="每 IP 每日注册次数"
                    ),
                ),
                (
                    "resend_verification_per_ip_per_hour",
                    models.PositiveIntegerField(
                        default=5, verbose_name="每 IP 每小时重发验证邮件次数"
                    ),
                ),
                (
                    "feedback_anon_per_ip_per_day",
                    models.PositiveIntegerField(
                        default=10, verbose_name="每 IP 每日匿名反馈次数"
                    ),
                ),
                (
                    "sync_upload_max_bytes",
                    models.PositiveBigIntegerField(
                        default=52428800,
                        help_text="任意类型走同步通路的上限；超过则仅图片/视频可走 tus。",
                        verbose_name="同步上传单文件上限（字节）",
                    ),
                ),
                (
                    "tus_media_max_bytes",
                    models.PositiveBigIntegerField(
                        default=524288000, verbose_name="tus 图/视频上限（字节）"
                    ),
                ),
            ],
            options={
                "verbose_name": "站点策略",
                "verbose_name_plural": "站点策略",
            },
        ),
    ]
