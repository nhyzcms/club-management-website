from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .lifecycle import (
    APPROVE_CLAIM,
    APPROVE_COMPLETION,
    ASSIGN,
    CANCEL,
    CLAIM,
    COMPLETE,
    KIND_FORBIDDEN,
    KIND_NOT_FOUND,
    REJECT_CLAIM,
    REJECT_COMPLETION,
    apply,
)
from common.models import Tag
from .models import Task, TaskClaimRequest
from .permissions import (
    CanAssignTask,
    CanCreateTask,
    CanManageTag,
    CanModifyTask,
    CanViewTask,
)
from accounts.permissions import IsVerified
from messaging.services import thread_for
from .serializers import (
    SimpleUserSerializer,
    TagSerializer,
    TaskClaimRequestSerializer,
    TaskDetailSerializer,
    TaskListSerializer,
)


class TagViewSet(viewsets.ModelViewSet):
    """标签管理（标签量小，关分页：前端表单一次性拉全量）"""
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated, CanManageTag]
    search_fields = ["name"]
    pagination_class = None


# apply 拒绝类别 → HTTP 状态码（默认 bad_request → 400）。
_KIND_STATUS = {
    KIND_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    KIND_NOT_FOUND: status.HTTP_404_NOT_FOUND,
}


class TaskViewSet(viewsets.ModelViewSet):
    """任务 CRUD"""
    queryset = Task.objects.select_related(
        "creator", "creator__profile",
        "assignee", "assignee__profile",
    ).prefetch_related(
        "tags",
        "collaborators", "collaborators__profile",
        "attachments",
        "claim_requests", "claim_requests__claimant", "claim_requests__claimant__profile",
    )

    filterset_fields = ["status", "priority", "assignee", "creator"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "completed_at", "priority", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return TaskListSerializer
        return TaskDetailSerializer

    # 身份门槛（#30）：建任务 / 认领 / 提交完成 / 取消 / 改删（pending）需身份已审核；
    # 审批类（approve_*/reject_*）与分派（assign，社长）不在新门槛范围（见 #26）。
    _VERIFIED_GATED = {"create", "claim", "complete", "cancel", "update", "partial_update", "destroy"}

    def get_permissions(self):
        if self.action == "create":
            perms = [IsAuthenticated(), CanCreateTask()]
        elif self.action in ("update", "partial_update", "destroy"):
            perms = [IsAuthenticated(), CanModifyTask()]
        elif self.action == "assign":
            perms = [IsAuthenticated(), CanAssignTask()]
        else:
            perms = [IsAuthenticated(), CanViewTask()]
        if self.action in self._VERIFIED_GATED:
            perms.append(IsVerified())
        return perms

    def get_queryset(self):
        return super().get_queryset()

    def list(self, request, *args, **kwargs):
        """列表：默认分页（20/页）；?all=1 逃生口返回全量裸数组（时间线/甘特图用）。"""
        if request.query_params.get("all") == "1":
            qs = self.filter_queryset(self.get_queryset())
            return Response(self.get_serializer(qs, many=True).data)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        task = serializer.save(creator=self.request.user)
        thread_for(task)

    def perform_update(self, serializer):
        serializer.save()

    def _respond_transition(self, result, request):
        """把生命周期模块的 TransitionResult 映射为 HTTP 响应。

        成功则回取带 prefetch 的任务、序列化（详情含 available_actions）返回 200；
        失败则按 ``kind`` 映射 403 / 404，其余（bad_request）默认 400。
        八个流转动作均退化为「解析入参 → apply → 本方法」的薄调用方。
        """
        if result.ok:
            task = self.get_queryset().get(pk=result.task.pk)
            return Response(TaskDetailSerializer(task, context={"request": request}).data)
        return Response(
            {"detail": result.reason},
            status=_KIND_STATUS.get(result.kind, status.HTTP_400_BAD_REQUEST),
        )

    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        """申请认领任务（成功返回该认领申请，201）"""
        task = self.get_object()
        result = apply(CLAIM, task, request.user, payload={"reason": request.data.get("reason", "")})
        if result.ok:
            return Response(TaskClaimRequestSerializer(result.claim).data, status=status.HTTP_201_CREATED)
        return self._respond_transition(result, request)

    @action(detail=True, methods=["post"])
    def approve_claim(self, request, pk=None):
        """批准认领请求"""
        task = self.get_object()
        return self._respond_transition(
            apply(APPROVE_CLAIM, task, request.user, payload={"claim_id": request.data.get("claim_id")}),
            request,
        )

    @action(detail=True, methods=["post"])
    def reject_claim(self, request, pk=None):
        """拒绝认领请求"""
        task = self.get_object()
        return self._respond_transition(
            apply(REJECT_CLAIM, task, request.user, payload={"claim_id": request.data.get("claim_id")}),
            request,
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """提交验收：活跃参与者（负责人 / 协作者）或社长完成工作，进入待验收"""
        task = self.get_object()
        return self._respond_transition(apply(COMPLETE, task, request.user), request)

    @action(detail=True, methods=["post"])
    def approve_completion(self, request, pk=None):
        """通过验收：发起人 / 社长确认，任务完成"""
        task = self.get_object()
        return self._respond_transition(apply(APPROVE_COMPLETION, task, request.user), request)

    @action(detail=True, methods=["post"])
    def reject_completion(self, request, pk=None):
        """打回：发起人 / 社长打回待验收任务，返回进行中（需填打回理由）"""
        task = self.get_object()
        return self._respond_transition(
            apply(REJECT_COMPLETION, task, request.user, payload={"reason": request.data.get("reason", "")}),
            request,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """取消任务"""
        task = self.get_object()
        return self._respond_transition(apply(CANCEL, task, request.user), request)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """社长直接指派（设 / 清负责人，联动状态）"""
        task = self.get_object()
        return self._respond_transition(
            apply(ASSIGN, task, request.user, payload={"assignee_id": request.data.get("assignee_id")}),
            request,
        )

    @action(detail=False, methods=["get"])
    def my_tasks(self, request):
        """当前用户的任务"""
        user = request.user
        qs = Task.objects.filter(
            Q(creator=user) | Q(assignee=user) | Q(collaborators=user)
        ).select_related(
            "creator", "assignee",
        ).prefetch_related("tags").distinct()
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = TaskListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = TaskListSerializer(qs, many=True)
        return Response(serializer.data)


# 旧的按任务内嵌只读附件 ViewSet 与上传/删除动作已移除：附件列表随父级详情返回，
# 上传/删除统一走独立 /attachments/ 端点（见 attachments app）。
