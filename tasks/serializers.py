from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from attachments.serializers import AttachmentSerializer

from .lifecycle import available_actions, status_for_assignee
from common.models import Tag
from .models import Task, TaskClaimRequest

# 新闻 / 活动详情序列化也复用（与 SimpleUserSerializer 同模式）。
_THREAD_STATUSES = ("open", "muted", "closed")


class CommentThreadHostMixin(serializers.Serializer):
    """宿主详情：写入 ``comment_thread_status``，读出 ``comment_thread``。

    只调用 ``messaging.services``，不 import 模型。
    """

    comment_thread_status = serializers.ChoiceField(
        choices=_THREAD_STATUSES, required=False, write_only=True,
    )
    comment_thread = serializers.SerializerMethodField()

    def get_comment_thread(self, obj):
        from messaging.services import can_manage_thread, thread_for

        thread = thread_for(obj)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return {
            "id": thread.pk,
            "status": thread.status,
            "can_manage": can_manage_thread(user, thread),
        }

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        self._comment_thread_status = value.pop("comment_thread_status", None)
        return value

    def apply_comment_thread_status(self, instance):
        status = getattr(self, "_comment_thread_status", None)
        if not status:
            return instance
        from messaging.services import MessagingError, MessagingForbidden, set_thread_status, thread_for

        request = self.context.get("request")
        user = getattr(request, "user", None)
        try:
            set_thread_status(thread_for(instance), user, status)
        except MessagingForbidden as exc:
            raise PermissionDenied(detail=exc.detail)
        except MessagingError as exc:
            raise serializers.ValidationError({"comment_thread_status": exc.detail})
        return instance


class SimpleUserSerializer(serializers.ModelSerializer):
    """轻量用户引用（id / username / nickname / avatar / is_deleted）。

    ``email`` 是私密字段，仅本人可见——与 ``accounts.visibility`` 的
    ``can_see_private = owner`` 对齐（见 accounts/tests_visibility.py 字段可见性
    矩阵）。此前 email 列在 ``fields`` 里无条件输出，使所有复用本序列化器的
    公开读接口（新闻 / 教程 / 活动等）随内容泄露他人邮箱；现改为在
    :meth:`to_representation` 中仅当查看者即本人时动态挂载。

    已注销账号（ADR-0025）：``is_deleted=True``，并把 username / avatar 置空、
    nickname 统一替换成「该用户已注销」——历史私信、评论、新闻作者位都靠这一处
    收口，前端 `nickname || username` 的老写法会自然显示该文案，不泄露旧昵称。
    """

    nickname = serializers.CharField(source="profile.nickname", default="")
    avatar = serializers.SerializerMethodField()
    is_deleted = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "nickname", "avatar", "is_deleted"]

    def get_avatar(self, obj):
        from accounts.models import is_deleted_user

        profile = getattr(obj, "profile", None)
        if profile and profile.avatar and not is_deleted_user(obj):
            return profile.avatar.url
        return None

    def get_is_deleted(self, obj):
        from accounts.models import is_deleted_user

        return is_deleted_user(obj)

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if data.get("is_deleted"):
            from accounts.models import DELETED_ACCOUNT_LABEL

            data["username"] = ""
            data["nickname"] = DELETED_ACCOUNT_LABEL
            data["avatar"] = None
            return data
        request = self.context.get("request")
        viewer = getattr(request, "user", None)
        if viewer is not None and viewer.is_authenticated and viewer.pk == obj.pk:
            data["email"] = obj.email
        return data


class TagSerializer(serializers.ModelSerializer):
    task_count = serializers.SerializerMethodField()

    class Meta:
        model = Tag
        fields = ["id", "name", "color", "task_count"]

    def get_task_count(self, obj):
        return obj.tasks.count()


class TaskClaimRequestSerializer(serializers.ModelSerializer):
    claimant = SimpleUserSerializer(read_only=True)
    # B2：模型字段统一为 moderated_by / moderated_at，对外名保持不变
    reviewed_by = SimpleUserSerializer(read_only=True, source="moderated_by")
    reviewed_at = serializers.DateTimeField(source="moderated_at", read_only=True)

    class Meta:
        model = TaskClaimRequest
        fields = [
            "id", "task", "claimant", "status",
            "reason", "reviewed_by", "reviewed_at", "created_at",
        ]
        read_only_fields = ["claimant", "status", "reviewed_by", "reviewed_at", "created_at"]


class TaskListSerializer(serializers.ModelSerializer):
    creator = SimpleUserSerializer(read_only=True)
    assignee = SimpleUserSerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    attachment_count = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "title", "status", "priority",
            "creator", "assignee", "tags",
            "completed_at",
            "reject_reason",
            "attachment_count",
            "created_at", "updated_at",
        ]

    def get_attachment_count(self, obj):
        return obj.attachments.count()


class TaskDetailSerializer(CommentThreadHostMixin, serializers.ModelSerializer):
    creator = SimpleUserSerializer(read_only=True)
    assignee = SimpleUserSerializer(read_only=True)
    collaborators = SimpleUserSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    claim_requests = TaskClaimRequestSerializer(many=True, read_only=True)
    available_actions = serializers.SerializerMethodField()

    assignee_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True, write_only=True,
        source="assignee",
    )
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False, write_only=True,
        source="tags",
    )
    collaborator_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), many=True, required=False, write_only=True,
        source="collaborators",
    )

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "status", "priority",
            "creator", "assignee", "assignee_id",
            "collaborators", "collaborator_ids",
            "tags", "tag_ids",
            "attachments", "claim_requests", "available_actions",
            "comment_thread", "comment_thread_status",
            "completed_at",
            "reject_reason",
            "created_at", "updated_at",
        ]
        read_only_fields = ["creator", "status", "completed_at", "reject_reason", "created_at", "updated_at"]

    def get_available_actions(self, task):
        """当前查看者可对该任务执行的动作（来自生命周期模块）。列表序列化不带此字段。"""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return []
        return available_actions(task, user)

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        collaborators = validated_data.pop("collaborators", [])
        # 负责人↔状态联动委托生命周期模块（与指派动作共用一处判定）。
        validated_data["status"] = status_for_assignee(validated_data.get("assignee"))
        task = Task.objects.create(**validated_data)
        if tags:
            task.tags.set(tags)
        if collaborators:
            task.collaborators.set(collaborators)
        return self.apply_comment_thread_status(task)

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        collaborators = validated_data.pop("collaborators", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        if collaborators is not None:
            instance.collaborators.set(collaborators)
        return self.apply_comment_thread_status(instance)
