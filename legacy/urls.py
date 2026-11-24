from django.urls import path, re_path

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
    # WebP 的 JPEG 兜底图；token 是 40 位十六进制内容哈希，格式不对的
    # 请求会落到下面的兜底路由，回 legacy 自己的 404 页。
    re_path(r"^img/(?P<token>[0-9a-f]{40}).jpg$", views.image, name="image"),
    # 兜底：/legacy/ 下任何没匹配上的路径都回 legacy 自己的 404 页，
    # 而不是 Django 默认的英文纯文本页。
    re_path(r"^.*$", views.not_found),
]