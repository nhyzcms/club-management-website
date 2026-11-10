from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from about.permissions import CanEditAbout
from activities.device import device_id_from_request
from activities.models import Questionnaire, QuestionnaireResponse

from .models import RecruitmentNotice
from .serializers import (
    JoinQuestionnaireSerializer,
    JoinResponseSerializer,
    RecruitmentNoticeSerializer,
)
from .throttles import JoinAnswerThrottle


class IsAboutEditor(BasePermission):
    """招生作答列表等敏感读：必须持 about.manage_aboutpage。"""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("about.manage_aboutpage"))


# 加入（自我介绍）问卷：同一人（登录按 user / 游客按设备）最多提交次数。
JOIN_MAX_SUBMISSIONS = 5


def _join_response_count(questionnaire, request):
    """当前请求者（登录按 user / 游客按 device）在加入问卷上的已提交次数。"""
    user = request.user if request.user.is_authenticated else None
    if user is not None:
        return questionnaire.responses.filter(user=user).count()
    device_id = device_id_from_request(request)
    if not device_id:
        return 0
    return questionnaire.responses.filter(user__isnull=True, device_id=device_id).count()


def _already_responded(questionnaire, request):
    return _join_response_count(questionnaire, request) > 0


class RecruitmentLandingView(APIView):
    """GET /recruitment/：公告 + 问卷 Schema，公开可读。"""

    permission_classes = [AllowAny]

    def get(self, request):
        notice = RecruitmentNotice.objects.get_solo()
        questionnaire = Questionnaire.get_join()
        count = _join_response_count(questionnaire, request)
        return Response({
            "notice": RecruitmentNoticeSerializer(notice).data,
            "schema": questionnaire.schema,
            "already_responded": count > 0,
            "responded_count": count,
            "max_submissions": JOIN_MAX_SUBMISSIONS,
        })


class RecruitmentNoticeView(RetrieveUpdateAPIView):
    serializer_class = RecruitmentNoticeSerializer
    permission_classes = [CanEditAbout]
    http_method_names = ["get", "put", "patch", "head", "options"]

    def get_object(self):
        return RecruitmentNotice.objects.get_solo()


class JoinQuestionnaireView(RetrieveUpdateAPIView):
    serializer_class = JoinQuestionnaireSerializer
    permission_classes = [CanEditAbout]
    http_method_names = ["get", "put", "patch", "head", "options"]

    def get_object(self):
        return Questionnaire.get_join()


class JoinResponseView(ListCreateAPIView):
    serializer_class = JoinResponseSerializer

    def get_throttles(self):
        # 只限提交，不限编辑查看列表（审计 M-3）。
        if self.request.method == "POST":
            return [JoinAnswerThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        return Questionnaire.get_join().responses.all()

    def get_permissions(self):
        if self.request.method == "POST":
            return [AllowAny()]
        return [IsAboutEditor()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        questionnaire = Questionnaire.get_join()
        user = request.user if request.user.is_authenticated else None
        device_id = device_id_from_request(request)
        if user is None:
            if not device_id:
                return Response({"detail": "缺少设备标识"}, status=status.HTTP_400_BAD_REQUEST)
            count = questionnaire.responses.filter(
                user__isnull=True, device_id=device_id,
            ).count()
        else:
            count = questionnaire.responses.filter(user=user).count()
        if count >= JOIN_MAX_SUBMISSIONS:
            return Response(
                {"detail": f"最多可提交 {JOIN_MAX_SUBMISSIONS} 次，你已达到上限。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            with transaction.atomic():
                instance = serializer.save(
                    questionnaire=questionnaire,
                    user=user,
                    device_id=device_id if user is None else "",
                )
        except IntegrityError:
            return Response({"detail": "提交失败，请稍后重试。"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"ok": True, "id": instance.pk, "message": "报名已提交，我们会尽快与你联系。"},
            status=status.HTTP_201_CREATED,
        )
