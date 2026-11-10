from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AboutBlockViewSet, AboutPageView, ClubOverviewView

router = DefaultRouter()
router.register(r"blocks", AboutBlockViewSet, basename="about-block")

urlpatterns = [
    path("", AboutPageView.as_view(), name="about-detail"),
    path("overview/", ClubOverviewView.as_view(), name="about-overview"),
    path("", include(router.urls)),
]
