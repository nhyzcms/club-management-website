from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import FeedbackViewSet, ReportCaseViewSet, ReviewViewSet

router = DefaultRouter()
router.register(r"reviews", ReviewViewSet, basename="review")
router.register(r"feedbacks", FeedbackViewSet, basename="feedback")
router.register(r"reports", ReportCaseViewSet, basename="reportcase")

urlpatterns = [
    path("", include(router.urls)),
]
