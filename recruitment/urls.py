from django.urls import path

from .views import (
    JoinQuestionnaireView,
    JoinResponseView,
    RecruitmentLandingView,
    RecruitmentNoticeView,
)

urlpatterns = [
    path("", RecruitmentLandingView.as_view(), name="recruitment-landing"),
    path("notice/", RecruitmentNoticeView.as_view(), name="recruitment-notice"),
    path("schema/", JoinQuestionnaireView.as_view(), name="recruitment-schema"),
    path("responses/", JoinResponseView.as_view(), name="recruitment-responses"),
]
