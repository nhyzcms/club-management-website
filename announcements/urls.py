from django.urls import path

from .views import (
    ActiveAnnouncementsView,
    AnnouncementDetailView,
    AnnouncementReadView,
    announcement_file_view,
)

urlpatterns = [
    path("active/", ActiveAnnouncementsView.as_view(), name="announcement-active"),
    path("<int:pk>/", AnnouncementDetailView.as_view(), name="announcement-detail"),
    path("<int:pk>/read/", AnnouncementReadView.as_view(), name="announcement-read"),
    path("<int:pk>/file/", announcement_file_view, name="announcement-file"),
]
