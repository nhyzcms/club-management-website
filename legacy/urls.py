from django.urls import path

from . import views

app_name = "legacy"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
]
