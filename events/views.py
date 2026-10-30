"""活动视图集（2026-10）。

读：公开受众的活动游客可见；成员可见全部非草稿；草稿仅组织者与管理者。
写：创建需已认证；编辑 / 发布 / 归档需组织者或 ``events.manage_events``。
「到点自动关闭」由 ``lifecycle.touch()`` 在每次读取时惰性推进，写入口再判
``can_edit`` —— 已结束的活动改不动，也不需要定时任务。
"""
from django.db.models import Q
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsVerified

from . import lifecycle
from .models import Event
from .permissions import CanCreateEvent, CanModifyEvent
from .serializers import EventSerializer


class EventViewSet(viewsets.ModelViewSet):
    """活动：一段有明确起止的时间窗，参与方式由 module_key 决定。"""

    serializer_class = EventSerializer
    filterset_fields = ["status", "visibility", "module_key"]
    search_fields = ["title", "summary", "body"]
    ordering_fields = ["start_at", "end_at", "created_at"]
    ordering = ["-start_at", "-id"]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsVerified(), CanCreateEvent()]
        if self.action in ("update", "partial_update", "destroy", "publish", "archive"):
            return [IsAuthenticated(), CanModifyEvent()]
        return [AllowAny()]

    def get_queryset(self):
        # 惰性流转：到点的 scheduled → active、active → ended，先推进再判断可见性。
        lifecycle.touch()
        qs = Event.objects.select_related("organizer")
        user = self.request.user
        if user.is_authenticated and user.has_perm("events.manage_events"):
            return qs
        if user.is_authenticated:
            # 成员：全部非草稿 + 自己发起的草稿
            return qs.filter(
                ~Q(status=Event.STATUS_DRAFT) | Q(organizer=user)
            )
        # 游客：仅公开受众，且不含草稿
        return qs.filter(
            visibility=Event.VISIBILITY_PUBLIC,
        ).exclude(status=Event.STATUS_DRAFT)

    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user, status=Event.STATUS_DRAFT)

    def perform_update(self, serializer):
        event = self.get_object()
        if not lifecycle.can_edit(event, self.request.user):
            raise PermissionDenied("活动已开始，仅草稿或待开始期间可修改")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.status != Event.STATUS_DRAFT:
            raise PermissionDenied("仅草稿可以删除；已发布的活动请归档")
        instance.delete()

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        """发布草稿：按 start_at 落到 scheduled 或 active。"""
        event = self.get_object()
        if not lifecycle.can_publish(event, request.user):
            raise ValidationError({"detail": "只有草稿可以发布"})
        lifecycle.publish(event)
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """归档已结束的活动：从默认列表收起，数据保留。"""
        event = self.get_object()
        if not lifecycle.can_archive(event, request.user):
            raise ValidationError({"detail": "只有已结束的活动可以归档"})
        Event.objects.filter(pk=event.pk, status=Event.STATUS_ENDED).update(
            status=Event.STATUS_ARCHIVED, updated_at=timezone.now(),
        )
        event.refresh_from_db()
        return Response(self.get_serializer(event).data, status=http_status.HTTP_200_OK)
