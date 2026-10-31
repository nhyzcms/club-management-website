from django.db.models import F
import hashlib
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.permissions import IsVerified
from accounts.utils import get_client_ip
from reviews.lifecycle import open_review, reopen_on_edit
from reviews.models import Review
from reviews.visibility import status_of, visible_queryset

from .models import Tutorial, TutorialFavorite, TutorialView
from .permissions import CanModifyTutorial, CanViewTutorial
from .serializers import (
    TutorialDetailSerializer,
    TutorialListSerializer,
    validate_tutorial_upload,
)


class TutorialViewSet(viewsets.ModelViewSet):
    """教程集锦：公开读已过审；已认证成员可上传；收藏 + 去重播放量。"""

    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ["file_type"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "views"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Tutorial.objects.select_related(
            "uploader", "uploader__profile", "review",
        ).prefetch_related("favorites")
        user = self.request.user
        if self.action == "list":
            return visible_queryset(qs, user, "tutorial", action="list")
        if self.action == "mine" and user.is_authenticated:
            return qs.filter(uploader=user)
        return visible_queryset(qs, user, "tutorial", action="retrieve")

    def get_serializer_class(self):
        if self.action == "list":
            return TutorialListSerializer
        return TutorialDetailSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [CanViewTutorial()]
        if self.action == "create":
            return [IsVerified()]
        if self.action in ("favorite", "mine"):
            return [IsVerified()]
        if self.action in ("update", "partial_update", "destroy"):
            return [CanModifyTutorial()]
        return [CanViewTutorial()]

    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "请上传视频或文档"}, status=status.HTTP_400_BAD_REQUEST)
        file_type = validate_tutorial_upload(upload)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"detail": "请填写标题"}, status=status.HTTP_400_BAD_REQUEST)
        tutorial = Tutorial.objects.create(
            title=title[:200],
            description=(request.data.get("description") or "")[:2000],
            file=upload,
            file_type=file_type,
            file_name=upload.name,
            file_size=upload.size,
            cover=request.FILES.get("cover") or "",
            uploader=request.user,
        )
        open_review(tutorial=tutorial, actor=request.user)
        serializer = TutorialDetailSerializer(tutorial, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        """标题 / 简介是实质内容：已过审后再改须重新入审（审计 H-5）。

        ``file_type`` / ``file_name`` / ``file_size`` / ``views`` 由服务端派生，
        序列化器已设为只读，客户端改不动。
        """
        incoming = set(serializer.validated_data)
        tutorial = serializer.save()
        if incoming & {"title", "description"} and reopen_on_edit(
            tutorial=tutorial, actor=self.request.user
        ):
            # 序列化器可能已缓存旧 review 关系；清掉缓存，让响应反映 pending。
            tutorial.refresh_from_db()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if status_of(instance) == Review.STATUS_APPROVED:
            if request.user.is_authenticated:
                reader_key = f"user:{request.user.pk}"
            else:
                ip = get_client_ip(request) or ""
                reader_key = "ip:" + hashlib.sha256(ip.encode()).hexdigest()
            _, created = TutorialView.objects.get_or_create(tutorial=instance, reader_key=reader_key)
            if created:
                Tutorial.objects.filter(pk=instance.pk).update(views=F("views") + 1)
                instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=["get"])
    def mine(self, request):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        ser = TutorialListSerializer(page or qs, many=True, context={"request": request})
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)

    @action(detail=True, methods=["post"])
    def favorite(self, request, pk=None):
        tutorial = self.get_object()
        existing = TutorialFavorite.objects.filter(tutorial=tutorial, user=request.user).first()
        if existing:
            existing.delete()
            favorited = False
        else:
            TutorialFavorite.objects.create(tutorial=tutorial, user=request.user)
            favorited = True
        tutorial.refresh_from_db()
        data = self.get_serializer(tutorial).data
        data["favorited"] = favorited
        data["favorite_count"] = TutorialFavorite.objects.filter(tutorial=tutorial).count()
        return Response(data)
