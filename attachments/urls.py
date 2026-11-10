from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import AttachmentViewSet

# SimpleRouter（无根 API 视图，避免与列表视图在 /attachments/ 撞）。
# 资源前缀为空：由根 URL 的 ``attachments/`` 挂载提供 → /attachments/ 与 /attachments/{id}/。
router = SimpleRouter()
router.register(r"", AttachmentViewSet, basename="unified-attachment")

urlpatterns = [
    path("", include(router.urls)),
]
