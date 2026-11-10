from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PanoramaViewSet

router = DefaultRouter()
router.register(r"panoramas", PanoramaViewSet, basename="panorama")

urlpatterns = [
    path("", include(router.urls)),
]
