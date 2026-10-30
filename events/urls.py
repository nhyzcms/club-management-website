"""活动 API 路由：挂在 ``/events/`` 下（list/detail + publish/archive）。"""
from rest_framework.routers import SimpleRouter

from .views import EventViewSet

router = SimpleRouter()
router.register("", EventViewSet, basename="event")

urlpatterns = router.urls
