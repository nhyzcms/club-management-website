from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "messaging"
    verbose_name = "站内通信"

    def ready(self):
        # import 即注册（通知源与通道是代码级注册表）
        from .notifications import channels, sources  # noqa: F401
