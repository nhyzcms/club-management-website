from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from common.throttles import PublicReadThrottle

from .models import Panorama
from .permissions import CanManagePanorama, CanViewPanorama
from .serializers import PanoramaDetailSerializer, PanoramaListSerializer
from .services import PanoramaImportError, import_panorama, process_panorama


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class PanoramaViewSet(viewsets.ModelViewSet):
    """校园全景图：公开读已发布；持 ``panorama.manage_panoramas`` 者增删改。

    读走「身份 + 可见性」不门禁权限（ADR-0005 决策 8）：公开侧只出
    ``is_published=True`` 且 ``status=ready`` 的条目，管理者可见全部
    （含切片中 / 切片失败，便于排查）。
    """

    parser_classes = [JSONParser, MultiPartParser, FormParser]
    # 审计 #280：列表 / 详情是公开读，且 search_fields 走 SQLite LIKE，
    # 此前无任何限流。只计 GET/HEAD/OPTIONS，上传 / 切片等写操作不受影响。
    throttle_classes = [PublicReadThrottle]
    filterset_fields = ["origin", "status"]
    search_fields = ["title", "description", "device_model"]
    ordering_fields = ["order", "created_at", "updated_at"]
    ordering = ["order", "-created_at"]

    def _can_manage(self) -> bool:
        user = self.request.user
        return bool(
            user.is_authenticated and user.has_perm("panorama.manage_panoramas")
        )

    def get_queryset(self):
        queryset = Panorama.objects.select_related("created_by")
        if self._can_manage():
            return queryset
        return queryset.filter(is_published=True, status=Panorama.STATUS_READY)

    def get_serializer_class(self):
        if self.action == "list":
            return PanoramaListSerializer
        return PanoramaDetailSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [CanViewPanorama()]
        return [CanManagePanorama()]

    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("source") or request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "请上传全景图（等距柱状 JPEG，或装着全景图的 zip）"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"detail": "请填写标题"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            panorama = import_panorama(
                upload=upload,
                title=title,
                description=(request.data.get("description") or ""),
                order=max(0, min(_as_int(request.data.get("order"), 0), 9999)),
                is_published=_as_bool(request.data.get("is_published"), True),
                user=request.user if request.user.is_authenticated else None,
            )
        except PanoramaImportError as exc:
            return Response(
                {"detail": str(exc), "reason": exc.reason},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            PanoramaDetailSerializer(panorama, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def reprocess(self, request, pk=None):
        """重新切片：换源图 / 切片失败后重来 / 调层级重来。"""
        panorama = self.get_object()
        if not panorama.source:
            return Response(
                {"detail": "该条目没有可用的原图，请重新上传。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            process_panorama(panorama)
        except Exception as exc:  # noqa: BLE001 —— 切片失败如实回报，不 500
            panorama.status = Panorama.STATUS_FAILED
            panorama.error = f"{exc.__class__.__name__}: {exc}"[:2000]
            panorama.save(update_fields=["status", "error", "updated_at"])
            return Response(
                {"detail": f"切片失败：{exc}", "reason": "processing_failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(PanoramaDetailSerializer(panorama, context={"request": request}).data)
