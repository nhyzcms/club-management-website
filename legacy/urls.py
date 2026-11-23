from django.urls import path

from . import views

app_name = "legacy"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("news/", views.news_list, name="news_list"),
    path("news/<int:pk>/", views.news_detail, name="news_detail"),
    path("activities/", views.activities_list, name="activities_list"),
    path("activities/<int:pk>/", views.activity_detail, name="activity_detail"),
    path("tutorials/", views.tutorials_list, name="tutorials_list"),
    path("tutorials/<int:pk>/", views.tutorial_detail, name="tutorial_detail"),
]