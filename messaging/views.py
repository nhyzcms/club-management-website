from collections import defaultdict

from django.contrib.auth.models import User
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsVerified
from activities.models import Activity
from common.policy import get_policy
from news.models import News
from tasks.models import Task

from .models import (
    Comment,
    CommentThread,
    Conversation,
    Message,
    Notification,
    unread_message_count,
)
from .notifications.preferences import PreferencesError, apply_updates, build_preferences
from .permissions import (
    CanManageThread,
    CanMuteUser,
    IsConversationParticipant,
    IsNotMuted,
)
from .serializers import (
    BannerSerializer,
    CommentSerializer,
    CommentThreadSerializer,
    ConversationSerializer,
    MessageSerializer,
    NotificationSerializer,
    UserMuteSerializer,
)
from reviews.discipline import current_mute, lift_mute, mute_user

from .services import (
    MessagingError,
    MessagingNotFound,
    can_see_host,
    can_see_thread,
    current_banner,
    delete_comment,
    mark_conversation_read,
    post_comment,
    retract_comment,
    retract_dm,
    send_dm,
    set_thread_status,
    start_private,
    thread_for,
)

_HOST_MODELS = {"news": News, "activity": Activity, "task": Task}


def _thread_qs():
    return CommentThread.objects.select_related(
        "news", "news__author", "news__review",
        "activity", "activity__creator", "activity__publication_review",
        "task", "task__creator",
    )


def _error_response(exc: MessagingError):
    return Response({"detail": exc.detail}, status=exc.status)


def _host_from_query(request):
    params = request.query_params
    keys = [k for k in ("news", "activity", "task") if params.get(k)]
    if len(keys) != 1:
        raise MessagingError("请指定恰好一个宿主：news、activity 或 task")
    key = keys[0]
    model = _HOST_MODELS[key]
    try:
        return model.objects.get(pk=params.get(key))
    except (model.DoesNotExist, ValueError, TypeError):
        raise MessagingNotFound("宿主不存在") from None


class CommentThreadViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """按宿主取恰好一条评论区；PATCH 改状态。"""

    serializer_class = CommentThreadSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return _thread_qs()

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "partial_update":
            return [IsAuthenticated(), CanManageThread()]
        return [IsAuthenticated()]

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup = self.lookup_url_kwarg or self.lookup_field
        obj = get_object_or_404(queryset, **{self.lookup_field: self.kwargs[lookup]})
        if not can_see_thread(self.request.user, obj):
            raise Http404
        self.check_object_permissions(self.request, obj)
        return obj

    def list(self, request):
        try:
            host = _host_from_query(request)
        except MessagingError as exc:
            return _error_response(exc)
        if not can_see_host(request.user, host):
            return Response({"detail": "评论区不存在"}, status=status.HTTP_404_NOT_FOUND)
        thread = thread_for(host)
        if not can_see_thread(request.user, thread):
            return Response({"detail": "评论区不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(thread).data)

    def partial_update(self, request, pk=None):
        thread = self.get_object()
        new_status = request.data.get("status")
        try:
            thread = set_thread_status(thread, request.user, new_status)
        except MessagingError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(thread).data)


class CommentViewSet(viewsets.GenericViewSet):
    """根评论分页，子评论嵌在同一 payload；POST 发表 / 撤回 / 协管删除。"""

    serializer_class = CommentSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Comment.objects.select_related(
            "author", "author__profile",
            "thread", "thread__news", "thread__activity", "thread__task",
        )

    def get_permissions(self):
        if self.action == "list":
            return [AllowAny()]
        if self.action == "create":
            return [IsAuthenticated(), IsVerified(), IsNotMuted()]
        if self.action == "retract":
            return [IsAuthenticated()]
        if self.action == "tombstone":
            return [IsAuthenticated(), CanManageThread()]
        return [IsAuthenticated()]

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup = self.lookup_url_kwarg or self.lookup_field
        obj = get_object_or_404(queryset, **{self.lookup_field: self.kwargs[lookup]})
        if not can_see_thread(self.request.user, obj.thread):
            raise Http404
        self.check_object_permissions(self.request, obj)
        return obj

    def list(self, request):
        thread_id = request.query_params.get("thread")
        if not thread_id:
            return Response({"detail": "缺少 thread"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            thread = _thread_qs().get(pk=thread_id)
        except (CommentThread.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "评论区不存在"}, status=status.HTTP_404_NOT_FOUND)
        if not can_see_thread(request.user, thread):
            return Response({"detail": "评论区不存在"}, status=status.HTTP_404_NOT_FOUND)

        children_map = defaultdict(list)
        for comment in (
            thread.comments
            .select_related("author", "author__profile")
            .order_by("created_at")
        ):
            children_map[comment.parent_id].append(comment)

        roots = (
            thread.comments
            .filter(parent__isnull=True)
            .select_related("author", "author__profile")
            .order_by("created_at")
        )
        page = self.paginate_queryset(roots)
        ctx = {**self.get_serializer_context(), "children_map": children_map}
        if page is not None:
            return self.get_paginated_response(CommentSerializer(page, many=True, context=ctx).data)
        return Response(CommentSerializer(roots, many=True, context=ctx).data)

    def create(self, request):
        if not get_policy().comments_enabled:
            return Response({"detail": "评论功能已关闭"}, status=status.HTTP_403_FORBIDDEN)
        thread_id = request.data.get("thread")
        if not thread_id:
            return Response({"detail": "缺少 thread"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            thread = _thread_qs().get(pk=thread_id)
        except (CommentThread.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "评论区不存在"}, status=status.HTTP_404_NOT_FOUND)
        parent = None
        parent_id = request.data.get("parent")
        if parent_id:
            try:
                parent = Comment.objects.get(pk=parent_id, thread=thread)
            except (Comment.DoesNotExist, ValueError, TypeError):
                return Response({"detail": "父评论不存在"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            comment = post_comment(
                thread, request.user, request.data.get("content", ""), parent=parent,
            )
        except MessagingError as exc:
            return _error_response(exc)
        return Response(
            CommentSerializer(comment, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def retract(self, request, pk=None):
        comment = self.get_object()
        try:
            comment = retract_comment(comment, request.user)
        except MessagingError as exc:
            return _error_response(exc)
        return Response(CommentSerializer(comment, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="delete")
    def tombstone(self, request, pk=None):
        comment = self.get_object()
        try:
            comment = delete_comment(comment, request.user)
        except MessagingError as exc:
            return _error_response(exc)
        return Response(CommentSerializer(comment, context=self.get_serializer_context()).data)


class ConversationViewSet(viewsets.ModelViewSet):
    """1:1 私信。不再提供任务/申报会话。"""

    serializer_class = ConversationSerializer
    http_method_names = ["get", "post", "head", "options"]

    _VERIFIED_GATED = {"send_message", "start_private"}
    _MUTE_GATED = {"send_message", "start_private"}

    def get_permissions(self):
        perms = [IsAuthenticated(), IsConversationParticipant()]
        if self.action in self._VERIFIED_GATED:
            perms.append(IsVerified())
        if self.action in self._MUTE_GATED:
            perms.append(IsNotMuted())
        return perms

    def get_queryset(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        return (
            Conversation.objects
            .filter(participants=self.request.user)
            .order_by("-updated_at", "-id")
            .prefetch_related(
                "participants", "participants__profile",
                "messages", "messages__sender", "messages__sender__profile",
            )
        )

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "请使用 start_private 发起私信。"},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def send_message(self, request, pk=None):
        if not get_policy().dms_enabled:
            return Response({"detail": "私信功能已关闭"}, status=status.HTTP_403_FORBIDDEN)
        conversation = self.get_object()
        try:
            message = send_dm(conversation, request.user, request.data.get("content", ""))
        except MessagingError as exc:
            return _error_response(exc)
        return Response(
            MessageSerializer(message, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def retract_message(self, request, pk=None):
        conversation = self.get_object()
        message_id = request.data.get("message_id")
        if not message_id:
            return Response({"detail": "缺少 message_id"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            message = conversation.messages.get(pk=message_id)
        except (Message.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "消息不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            message = retract_dm(message, request.user)
        except MessagingError as exc:
            return _error_response(exc)
        return Response(MessageSerializer(message, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"total": unread_message_count(request.user)})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """标会话已读；并把该会话的未读站内通知一并标已读（见 mark_conversation_read）。"""
        conversation = self.get_object()
        mark_conversation_read(request.user, conversation)
        return Response({"detail": "已标记为已读"})

    @action(detail=False, methods=["get"])
    def messages(self, request):
        """倒序分页（最新在前）：前端「最新优先 + 向上加载更早」。"""
        conversation_id = request.query_params.get("conversation_id")
        if not conversation_id:
            return Response({"detail": "缺少 conversation_id"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            conversation = Conversation.objects.get(pk=conversation_id, participants=request.user)
        except Conversation.DoesNotExist:
            return Response({"detail": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)

        messages = (
            conversation.messages
            .select_related("sender", "sender__profile")
            .prefetch_related("mentions", "mentions__profile")
            .order_by("-created_at")
        )
        page = self.paginate_queryset(messages)
        if page is not None:
            serializer = MessageSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        return Response(MessageSerializer(messages, many=True, context={"request": request}).data)

    @action(detail=False, methods=["post"])
    def start_private(self, request):
        if not get_policy().dms_enabled:
            return Response({"detail": "私信功能已关闭"}, status=status.HTTP_403_FORBIDDEN)
        target_id = request.data.get("user_id")
        if not target_id:
            return Response({"detail": "缺少 user_id"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            target = User.objects.get(pk=int(target_id))
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            conversation, created = start_private(request.user, target)
        except MessagingError as exc:
            return _error_response(exc)
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            Notification.objects
            .filter(recipient=self.request.user)
            .order_by("-created_at")
        )

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        total = self.get_queryset().filter(read_at__isnull=True).count()
        return Response({"total": total})

    @action(detail=True, methods=["post"], url_path="mark_read")
    def mark_one_read(self, request, pk=None):
        obj = self.get_object()
        if obj.read_at is None:
            obj.read_at = timezone.now()
            obj.save(update_fields=["read_at"])
        return Response(self.get_serializer(obj).data)

    @action(detail=False, methods=["post"], url_path="mark_read")
    def mark_all_read(self, request):
        self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"detail": "已全部标为已读"})


class MuteViewSet(viewsets.ViewSet):
    def get_permissions(self):
        if self.action == "me":
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanMuteUser()]

    def create(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"detail": "缺少 user_id"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            target = User.objects.get(pk=int(user_id))
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        ends_at = None
        raw = request.data.get("ends_at")
        if raw:
            ends_at = parse_datetime(str(raw))
            if ends_at is None:
                return Response({"detail": "ends_at 格式无效"}, status=status.HTTP_400_BAD_REQUEST)
            if timezone.is_naive(ends_at):
                ends_at = timezone.make_aware(ends_at)
        try:
            row = mute_user(
                request.user, target,
                reason=request.data.get("reason") or "",
                ends_at=ends_at,
            )
        except MessagingError as exc:
            return _error_response(exc)
        return Response(UserMuteSerializer(row).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def lift(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"detail": "缺少 user_id"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            target = User.objects.get(pk=int(user_id))
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            row = lift_mute(request.user, target)
        except MessagingError as exc:
            return _error_response(exc)
        return Response(UserMuteSerializer(row).data)

    @action(detail=False, methods=["get"])
    def me(self, request):
        row = current_mute(request.user)
        return Response({
            "muted": row is not None,
            "mute": UserMuteSerializer(row).data if row else None,
        })


class BannerViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["get"])
    def current(self, request):
        banner = current_banner()
        if banner is None:
            # DRF Response(None) is an empty body, not JSON null; 204 matches
            # frontend readResponse (empty banner → null).
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(BannerSerializer(banner).data)


class NotificationPreferencesView(APIView):
    """通知订阅偏好：GET 读矩阵；PATCH 应用变更（源 × 通道）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(build_preferences(request.user))

    def patch(self, request):
        try:
            apply_updates(request.user, request.data.get("updates"))
        except PreferencesError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(build_preferences(request.user))
