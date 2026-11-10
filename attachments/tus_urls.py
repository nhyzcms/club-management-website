"""tus 端点路由：/uploads/files/（创建）、/uploads/files/<guid>/（分片/状态/终止）。

用 drf-tus 的 TusAPIRouter（HEAD→info、PATCH→partial_update 等映射）注册本项目自定义的
TusUploadViewSet（含父级/权限/尺寸/配额校验）。不引入 rest_framework_tus.urls，避免其硬编码
的 reverse 命名空间依赖。
"""
from django.urls import include, path
from rest_framework_tus.routers import TusAPIRouter

from .tus import TusUploadViewSet

router = TusAPIRouter()
router.register(r"files", TusUploadViewSet, basename="tus-upload")

urlpatterns = [
    path("", include(router.urls)),
]
