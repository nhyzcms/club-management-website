from django.utils.dateparse import parse_datetime
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsVerified
from accounts.turnstile import passes_turnstile, turnstile_error_response

from .feedback_lifecycle import FeedbackDenied, close as close_feedback, submit as submit_feedback
from .lifecycle import APPROVE, REJECT, REMOVE, TransitionDenied, apply
from .models import Feedback, ReportCase, Review
from .permissions import CanAccessFeedback, CanHandleReport, CanModerateReview, CanViewFeedback
from .report_lifecycle import ReportDenied, dismiss as dismiss_report, file as file_report, uphold as uphold_report
from .serializers import (
    FeedbackDetailSerializer,
    FeedbackListSerializer,
    ReportCaseSerializer,
    ReportCreateSerializer,
    ReviewSerializer,
)
from .throttles import FeedbackAnonThrottle, ReportDailyThrottle


class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    """统一审核队列：列出待审项，对新闻/活动执行通过、驳回、下架。"""

    serializer_class = ReviewSerializer
    filterset_fields = ["status"]
    ordering_fields = ["created_at", "reviewed_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Review.objects.select_related(
            "news", "activity", "tutorial",
            "reviewer", "reviewer__profile",
        )

    def get_permissions(self):
        return [IsAuthenticated(), CanModerateReview()]

    def _transition(self, request, action, *, comment=""):
        review = self.get_object()
        try:
            apply(action, review, request.user, comment=comment)
        except TransitionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ReviewSerializer(review, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._transition(request, APPROVE, comment=request.data.get("comment", ""))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._transition(request, REJECT, comment=request.data.get("comment", ""))

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        return self._transition(request, REMOVE, comment=request.data.get("comment", ""))


class FeedbackViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """意见反馈：公开提交；列表/了结需 read_feedback；详情允许署名创建人。"""

    filterset_fields = ["status", "category"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Feedback.objects.select_related(
            "creator", "creator__profile",
            "closed_by", "closed_by__profile",
        ).prefetch_related("attachments", "attachments__uploaded_by")
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        if user.has_perm("reviews.read_feedback"):
            return qs
        return qs.filter(creator=user)

    def get_serializer_class(self):
        if self.action == "list":
            return FeedbackListSerializer
        return FeedbackDetailSerializer

    def get_permissions(self):
        if self.action == "submit":
            return [AllowAny()]
        if self.action == "retrieve":
            return [IsAuthenticated(), CanAccessFeedback()]
        return [IsAuthenticated(), CanViewFeedback()]

    @action(detail=False, methods=["post"], url_path="submit",
            throttle_classes=[FeedbackAnonThrottle])
    def submit(self, request):
        """意见反馈：可匿名（默认）或署名（登录后显式选择）提交。"""
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        disclose_identity = bool(data.pop("disclose_identity", False))
        token = data.pop("turnstile_token", "") or ""
        if not request.user.is_authenticated and not passes_turnstile(request, token):
            return turnstile_error_response(drf=True)
        if disclose_identity and not request.user.is_authenticated:
            return Response(
                {"detail": "署名提交需要登录"}, status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = FeedbackDetailSerializer(data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        creator = request.user if (disclose_identity and request.user.is_authenticated) else None
        feedback = submit_feedback(
            title=serializer.validated_data["title"],
            description=serializer.validated_data.get("description", ""),
            category=serializer.validated_data["category"],
            contact=serializer.validated_data.get("contact", ""),
            creator=creator,
        )
        feedback = Feedback.objects.select_related(
            "creator", "creator__profile", "closed_by", "closed_by__profile",
        ).prefetch_related("attachments").get(pk=feedback.pk)
        return Response(
            FeedbackDetailSerializer(feedback, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        feedback = self.get_object()
        try:
            close_feedback(feedback, request.user, note=request.data.get("note", ""))
        except FeedbackDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(FeedbackDetailSerializer(feedback, context={"request": request}).data)


class ReportCaseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """举报案：已认证成员提交；列表/处理需 handle_report。"""

    serializer_class = ReportCaseSerializer
    filterset_fields = ["status"]
    ordering_fields = ["created_at", "resolved_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return ReportCase.objects.select_related(
            "news", "activity", "tutorial", "comment", "comment__author",
            "reported_user", "reported_user__profile",
            "resolved_by", "resolved_by__profile",
        ).prefetch_related("filings", "filings__reporter", "filings__reporter__profile")

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsVerified()]
        return [IsAuthenticated(), CanHandleReport()]

    def get_throttles(self):
        if self.action == "create":
            return [ReportDailyThrottle()]
        return []

    def create(self, request, *args, **kwargs):
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            case = file_report(
                actor=request.user,
                target_type=serializer.validated_data["target_type"],
                target_id=serializer.validated_data["target_id"],
                reason=serializer.validated_data["reason"],
            )
        except ReportDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "id": case.pk,
                "status": case.status,
                "target_type": serializer.validated_data["target_type"],
                "target_id": serializer.validated_data["target_id"],
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        case = self.get_object()
        try:
            dismiss_report(case, request.user, comment=request.data.get("comment", ""))
        except ReportDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ReportCaseSerializer(case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def uphold(self, request, pk=None):
        case = self.get_object()
        ends_at = _parse_ends_at(request.data.get("ends_at"))
        if request.data.get("ends_at") not in (None, "") and ends_at is None:
            return Response({"detail": "结束时间格式无效"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            uphold_report(
                case, request.user,
                comment=request.data.get("comment", ""),
                ends_at=ends_at,
            )
        except ReportDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        case = self.get_queryset().get(pk=case.pk)
        return Response(ReportCaseSerializer(case, context={"request": request}).data)


def _parse_ends_at(value):
    if value in (None, ""):
        return None
    if hasattr(value, "tzinfo"):
        return value
    parsed = parse_datetime(str(value))
    return parsed
