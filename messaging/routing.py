from django.urls import path

from .consumers import MessagingConsumer

websocket_urlpatterns = [
    path("ws/messaging/", MessagingConsumer.as_asgi()),
]
