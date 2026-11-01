from django.db.models import Count, Prefetch
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .clock import clock_payload
from .expiry import compute_errata_expiry, has_active_subject
from .models import Exam, ExamBatch, ExamErrata, ExamSubject
from .permissions import CanManageExam
from .push import broadcast
from .serializers import (
    ExamErrataSerializer,
    ExamListSerializer,
    ExamSerializer,
)


def _exam_queryset():
    return Exam.objects.prefetch_related(
        Prefetch(
            "batches",
            queryset=ExamBatch.objects.prefetch_related(
                Prefetch("subjects", queryset=ExamSubject.objects.all()),
            ),
        ),
    )


def _live_errata_qs(exam_id=None):
    qs = ExamErrata.objects.filter(dismissed_at__isnull=True).order_by("id")
    if exam_id is not None:
        qs = qs.filter(exam_id=exam_id)
    return qs


def _parse_exam_id(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _expire_due(exam_id=None):
    """本场已结束的误刊按 id 升序撤回，便于看板依次收走。"""
    now = timezone.now()
    qs = _live_errata_qs(exam_id).filter(expires_at__isnull=False, expires_at__lte=now)
    ids = list(qs.values_list("id", flat=True))
    if exam_id is not None and not has_active_subject(exam_id):
        leftover = _live_errata_qs(exam_id).exclude(pk__in=ids)
        ids.extend(leftover.values_list("id", flat=True))
    if not ids:
        return ids
    ExamErrata.objects.filter(pk__in=ids).update(dismissed_at=now)
    broadcast("errata_cleared", {"ids": ids, "exam_id": exam_id})
    return ids


class ExamViewSet(viewsets.ModelViewSet):
    """考试看板：公开读列表/详情/最新/授时；写需 exam_board.manage_exams。"""

    permission_classes = [CanManageExam]
    queryset = Exam.objects.all()
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self): # type: ignore
        if self.action == "list":
            return Exam.objects.annotate(batch_count=Count("batches", distinct=True)).order_by("-id")
        return _exam_queryset()

    def get_serializer_class(self): # type: ignore
        if self.action == "list":
            return ExamListSerializer
        return ExamSerializer

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user)
        broadcast("exam", {"exam_id": serializer.instance.pk})

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
        broadcast("exam", {"exam_id": serializer.instance.pk})

    def perform_destroy(self, instance):
        exam_id = instance.pk
        instance.delete()
        broadcast("exam", {"exam_id": exam_id})

    @action(detail=False, methods=["get"])
    def latest(self, request):
        exam = self.get_queryset().first()
        if exam is None:
            return Response({"status": "success", "data": None, "message": "数据库中暂无考试数据"})
        return Response({"status": "success", "data": ExamSerializer(exam, context={"request": request}).data})

    @action(detail=False, methods=["get"])
    def clock(self, request):
        return Response(clock_payload())


class ExamErrataViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """题目误刊：公开读当前一场考试的未撤回列表；写需 exam_board.manage_exams。"""

    permission_classes = [CanManageExam]
    serializer_class = ExamErrataSerializer
    queryset = ExamErrata.objects.all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @action(detail=False, methods=["get"])
    def current(self, request):
        exam_id = _parse_exam_id(request.query_params.get("exam"))
        # 必须显式指定考试：否则会把其他场次的误刊混进当前看板（审计 L-4）。
        if exam_id is None:
            return Response(
                {"status": "error", "message": "缺少 exam 参数"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _expire_due(exam_id)
        rows = _live_errata_qs(exam_id)
        return Response({"status": "success", "data": self.get_serializer(rows, many=True).data})

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = serializer.validated_data["exam"]
        batch_id = _parse_exam_id(request.data.get("batch"))
        if batch_id is not None and not ExamBatch.objects.filter(
            pk=batch_id, exam_id=exam.pk,
        ).exists():
            batch_id = None
        item = serializer.save(
            created_by=request.user,
            expires_at=compute_errata_expiry(exam.pk, batch_id),
        )
        payload = ExamErrataSerializer(item, context={"request": request}).data
        broadcast("errata", payload)
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def dismiss(self, request):
        exam_id = _parse_exam_id(request.data.get("exam") or request.query_params.get("exam"))
        # 必须显式指定考试：缺省不能作用于全部考试（审计 L-4）。
        if exam_id is None:
            return Response(
                {"status": "error", "message": "缺少 exam 参数"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = _live_errata_qs(exam_id)
        ids = list(qs.values_list("id", flat=True))
        updated = qs.update(dismissed_at=timezone.now()) if ids else 0
        if updated:
            broadcast("errata_cleared", {"ids": ids, "exam_id": exam_id})
        return Response({"status": "success", "dismissed": updated, "ids": ids})
