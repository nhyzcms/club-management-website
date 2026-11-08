"""活动 API 路由：挂在 ``/events/`` 下（list/detail + publish/archive + 形态模块）。"""
from rest_framework.routers import SimpleRouter

from .views import EventViewSet

from django.urls import include, path

router = SimpleRouter()
router.register("", EventViewSet, basename="event")

urlpatterns = router.urls + [
    # 形态模块路由：明信片互寄（/events/postcard/...）
    path("postcard/", include("events.modules.postcard.urls")),
]
