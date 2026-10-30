from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"
    verbose_name = "通用"

    def ready(self):
        """接上 ContentTarget 的宿主删除信号（B1）。

        放在 ready() 而不是模块顶层：信号需要全部模型就绪后才能 connect。
        ``connect_all`` 内部用 dispatch_uid 去重，重复 ready（测试里的 app
        重载）不会重复挂。
        """
        from .targets import connect_all

        connect_all()
