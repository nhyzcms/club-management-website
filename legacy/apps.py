from django.apps import AppConfig


class LegacyConfig(AppConfig):
    """旧浏览器只读版：服务端直出的纯 HTML 页面，不依赖任何前端构建产物。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "legacy"
    verbose_name = "旧浏览器只读版"
