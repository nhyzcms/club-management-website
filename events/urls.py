"""活动 API 路由。

历史上这里挂的是通用「活动」CRUD（``EventViewSet``）；2026-11 按产品决定撤销
该模块，只保留 ``Event`` 模型作为形态模块（明信片互寄）的壳，
因此 ``/events/`` 下只剩 ``/events/postcard/...``。
"""
from django.urls import include, path

urlpatterns = [
    # 形态模块路由：明信片互寄（/events/postcard/...）
    path("postcard/", include("events.modules.postcard.urls")),
]
