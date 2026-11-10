from django.urls import path

from .consumers import ExamBoardConsumer

websocket_urlpatterns = [
    path("ws/exam-board/", ExamBoardConsumer.as_asgi()),
]
