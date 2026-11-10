from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ExamErrataViewSet, ExamViewSet

router = DefaultRouter()
router.register(r"exams", ExamViewSet, basename="exam")
router.register(r"errata", ExamErrataViewSet, basename="exam-errata")

urlpatterns = [
    path("", include(router.urls)),
]
