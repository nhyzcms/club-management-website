from django.apps import AppConfig


class EventsConfig(AppConfig):
    name = "events"
    verbose_name = "活动"

    def ready(self):
        """注册形态模块模型（modules 约定：模型定义在模块内、app_label 指向本 app）。

        ready() 是注册模型的标准时机（makemigrations 也会走到）；显式 import
        models 模块才会真正注册模型类。模块不存在时静默跳过，保证骨架阶段不炸。
        """
        try:
            from .modules.postcard import models as _postcard_models  # noqa: F401
            from .modules.postcard import signals as _postcard_signals  # noqa: F401
        except ImportError:
            pass
