from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework.mixins import RetrieveModelMixin, UpdateModelMixin

from .models import AboutBlock, AboutPage
from common.throttles import PublicReadThrottle

from .permissions import CanEditAbout
from .serializers import (
    AboutBlockSerializer,
    AboutOverviewSerializer,
    validate_about_document,
)


class AboutPageView(RetrieveUpdateAPIView):
    """GET /about/ 公开聚合；PUT /about/overview/ 由 ClubOverviewView 处理。

    本视图只做公开读：返回全部区块 + 社团概览静态行。
    """

    permission_classes = [CanEditAbout]
    http_method_names = ["get", "head", "options"]
    # 审计 #280：本视图一次吐出完整名册与联系方式（线上约 9KB），此前无任何限流。
    throttle_classes = [PublicReadThrottle]

    def get(self, request, *args, **kwargs):
        page = AboutPage.objects.get_solo()
        blocks = AboutBlock.objects.all()
        return Response({
            "blocks": AboutBlockSerializer(blocks, many=True, context={"request": request}).data,
            "overview": AboutOverviewSerializer(page).data,
            "updated_at": page.updated_at,
        })


class ClubOverviewView(RetrieveUpdateAPIView):
    """GET/PUT /about/overview/：社团概览静态行（成立 / 指导 / 简介）。"""

    serializer_class = AboutOverviewSerializer
    permission_classes = [CanEditAbout]
    http_method_names = ["get", "put", "patch", "head", "options"]
    # 审计 #280：只计 GET/HEAD/OPTIONS，PUT/PATCH 不占读额度（见 PublicReadThrottle）。
    throttle_classes = [PublicReadThrottle]

    def get_object(self):
        return AboutPage.objects.get_solo()


class AboutBlockViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    """GET/PATCH /about/blocks/<key>/：按键读写单个关于区块。"""

    serializer_class = AboutBlockSerializer
    permission_classes = [CanEditAbout]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    lookup_field = "key"
    queryset = AboutBlock.objects.all()
    http_method_names = ["get", "patch", "head", "options"]
    # 审计 #280：与 /about/ 同一份数据，不挂限流就等于留了个绕过口。
    throttle_classes = [PublicReadThrottle]

    def partial_update(self, request, *args, **kwargs):
        block = self.get_object()
        payload = {}
        for field in ("title", "content", "panorama_url"):
            if field in request.data:
                payload[field] = request.data.get(field)
        upload = request.FILES.get("document")
        if upload:
            validate_about_document(upload)
            if block.document:
                block.document.delete(save=False)
            block.document = upload
        elif str(request.data.get("clear_document", "")).lower() in ("1", "true", "yes"):
            if block.document:
                block.document.delete(save=False)
            block.document = ""

        serializer = self.get_serializer(block, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if upload or str(request.data.get("clear_document", "")).lower() in ("1", "true", "yes"):
            block.save(update_fields=["document", "updated_at"])
        return Response(self.get_serializer(block).data, status=status.HTTP_200_OK)
