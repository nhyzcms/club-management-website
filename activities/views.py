"""活动视图集（ADR 0007 / 0011）。

创建（已认证成员）+ 列表/详情（成员可读；访客仅公开调研）+ 正文图片上传。
众议投票 / 征集投稿复审 / 展示布展 / 调研作答。
"""
import os
import uuid

from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.models import is_verified
from accounts.permissions import IsVerified

from attachments.create import create_attachment
from attachments.validation import upload_error
from messaging.services import thread_for
from reviews.lifecycle import open_review
from reviews.models import Review
from reviews.visibility import status_of, visible_queryset

from . import exhibition, survey_search, voting
from .debt import annotate_activity_debt
from .device import client_ip_from_request, device_id_from_request
from .lifecycle import (
    CLOSED,
    COLLECTING,
    OPEN,
    REVIEWING,
    can_close,
    can_edit,
    can_edit_schema,
    can_rate,
    can_respond,
    can_submit,
    accepting_submissions,
    collection_close_target,
    maybe_close_collection_on_cap,
    order_activities,
    transition_due_starts,
    transition_overdue,
    transition_overdue_collections,
)
from .models import (
    Activity, Exhibit, ExhibitRating,
    QuestionnaireResponse, Submission,
)
from .permissions import (
    CanCreateActivity,
    CanModifyActivity,
    CanReviewSubmission,
)
from .serializers import ActivityDetailSerializer, ActivityListSerializer

# 正文内嵌图片上限（与新闻一致）
_CONTENT_IMAGE_MAX_SIZE = 5 * 1024 * 1024
_CONTENT_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def _content_image_path(filename):
    ext = os.path.splitext(filename)[1]
    return f"activity_content_images/{uuid.uuid4().hex}{ext}"


# 问卷文件题：允许的 content-type（图片 + PDF）
_SURVEY_UPLOAD_TYPES = (
    "image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf",
)


def _survey_upload_path(filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"survey_uploads/{uuid.uuid4().hex}{ext}"


def _parse_extensions(raw):
    """允许后缀配置串 → 集合：".jpg, .png" → {".jpg", ".png"}；空串 → 空集（=不限）。"""
    if not raw:
        return set()
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


class ActivityViewSet(viewsets.ModelViewSet):
    """活动（众议/征集）：已认证成员可发起与投票；成员可读。"""

    filterset_fields = ["type", "status", "creator"]
    search_fields = ["title", "body"]
    ordering_fields = ["created_at", "updated_at", "end_at"]
    # 默认顺序见 lifecycle.order_activities：进行中 / 待开始在前，已结束沉底，同档按发布时间倒序。
    # 客户端显式传 ?ordering= 时仍可覆盖（DRF OrderingFilter 后置）。
    ordering = ["_phase_rank", "-created_at"]

    def get_queryset(self):
        return order_activities(self._scoped_queryset())

    def _scoped_queryset(self):
        # 惰性流转（只维护 status 快照，供展示/筛选/排序；判定另有 state.calc_state）：
        # 到 start_at 的待开始活动自动开放；到 end_at 的众议/展示/调研自动结算；
        # 到 end_at 的征集自动结束收件（→ 复审 / 归档）。
        # 审核轴只门控可见性，不阻断上述状态机。
        transition_due_starts()
        transition_overdue()
        transition_overdue_collections()
        qs = Activity.objects.select_related(
            "creator", "creator__profile", "publication_review", "questionnaire",
        ).prefetch_related(
            "options", "options__selections",
            "ballots", "ballots__selections", "ballots__voter__profile",
            "submissions", "submissions__attachments", "submissions__submitter__profile",
            "submissions__moderated_by",
            "exhibits", "exhibits__attachments",
            "exhibits__vote_option", "exhibits__vote_option__selections",
            "exhibits__ratings",
        )
        user = self.request.user
        if not user.is_authenticated:
            # 访客：过审的公开调研 + 公开受众的众议/展示（公开投票入口；
            # 其他类型标题泄漏只走首页 feed）
            return visible_queryset(qs, user, "activity", action="list").filter(
                Q(type="survey", audience="public")
                | Q(type__in=("deliberation", "exhibition"), audience="public"),
            )
        if self.action == "mine":
            qs = qs.filter(creator=user)
        elif self.action == "list":
            qs = visible_queryset(qs, user, "activity", action="list")
        else:
            qs = visible_queryset(qs, user, "activity", action="retrieve")
        return annotate_activity_debt(qs, user)

    def get_serializer_class(self):
        if self.action == "list":
            return ActivityListSerializer
        if self.action == "mine":
            return ActivityListSerializer
        return ActivityDetailSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), CanCreateActivity(), IsVerified()]
        if self.action == "mine":
            return [IsAuthenticated()]
        if self.action in ("list", "retrieve", "respond"):
            return [AllowAny()]
        if self.action == "responses":
            return [IsAuthenticated()]
        if self.action == "vote":
            # 公开受众允许游客投票；成员受众的登录 / 认证门禁在视图内按受众把关。
            return [AllowAny()]
        if self.action == "submit":
            return [IsAuthenticated(), IsVerified()]
        if self.action == "rate":
            return [IsAuthenticated(), IsVerified()]
        if self.action == "review_submission":
            # 复审：发起人 OR 持 review_collection 权限（对象级）
            return [IsAuthenticated(), CanReviewSubmission()]
        if self.action == "close":
            # 提前关闭：发起人，或持 manage_activity 权限者（对象级）
            return [IsAuthenticated(), CanModifyActivity()]
        if self.action in ("add_exhibit", "update_exhibit", "delete_exhibit", "import_from_collection"):
            return [IsAuthenticated(), CanModifyActivity()]
        if self.action == "upload_image":
            # 正文插图：能发起活动的已认证成员即可（与创建同门禁）
            return [IsAuthenticated(), IsVerified()]
        if self.action == "survey_upload":
            # 问卷文件题：填答者含未登录游客（与 respond 同开放度），靠类型/大小限制兜底
            return [AllowAny()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), CanModifyActivity()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        activity = serializer.save(creator=self.request.user)
        open_review(activity=activity, actor=self.request.user)
        thread_for(activity)

    def perform_destroy(self, instance):
        """删除活动：只允许「零投稿 + 零选票」的活动。

        2026-10-31 审计 H-3：原先只要 CanModifyActivity 就放行，而
        ``Submission.activity`` / ``Ballot.activity`` 都是 CASCADE，
        ``Attachment`` 删除还会连带删磁盘文件 —— 发起人一次 DELETE 就能把别人的
        投稿、附件与选票审计记录全部抹掉，且不可恢复。

        收口原则取「不销毁他人数据」这一条最小面：空活动仍可随时删（保留既有 UX，
        清理误建活动不必先等结束），一旦有人投过稿 / 投过票就必须走下架。
        """
        from rest_framework.exceptions import PermissionDenied

        if instance.submissions.exists() or instance.ballots.exists():
            raise PermissionDenied("活动已有投稿或选票，不能直接删除（请改为下架）")
        super().perform_destroy(instance)

    @action(detail=False, methods=["get"])
    def mine(self, request):
        """作者预览：当前用户发起的全部活动（含待审/驳回/下架）。"""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = ActivityListSerializer(page or queryset, many=True, context={"request": request})
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def _serialized(self, activity, request, status_code=status.HTTP_200_OK):
        activity = self.get_queryset().get(pk=activity.pk)
        return Response(
            ActivityDetailSerializer(activity, context={"request": request}).data,
            status=status_code,
        )

    def create(self, request, *args, **kwargs):
        # 展示:展品在详情页布展(待开始期),创建只收标量——0 展品可建,走 JSON 通用路径。
        return super().create(request, *args, **kwargs)

    def perform_update(self, serializer):
        # 标题/正文/时间：仅待开始（scheduled）可改。
        # 调研 schema：待开始，或开放且尚无作答。受众不可改（序列化器已拦）。
        from rest_framework.exceptions import PermissionDenied

        instance = serializer.instance
        incoming = serializer.validated_data
        general_keys = [k for k in incoming if k not in ("schema", "audience")]
        if general_keys and not can_edit(instance):
            raise PermissionDenied("活动开放后不可修改，仅待开始期间可改")
        if "schema" in incoming:
            if instance.type == "survey":
                if not can_edit_schema(instance):
                    raise PermissionDenied("当前不可修改问卷")
            elif not can_edit(instance):
                raise PermissionDenied("活动开放后不可修改，仅待开始期间可改")
        elif not incoming and not can_edit(instance) and not getattr(serializer, "_comment_thread_status", None):
            raise PermissionDenied("活动开放后不可修改，仅待开始期间可改")
        super().perform_update(serializer)

    # ── 众议投票（公开受众任何人；仅成员须登录 + 已认证）──
    @action(detail=True, methods=["post"])
    def vote(self, request, pk=None):
        activity = self.get_object()  # 触发惰性结算（若已到点则已 closed）
        user = request.user if request.user.is_authenticated else None
        if activity.audience != "public":
            if user is None:
                return Response({"detail": "仅成员可投票，请先登录"}, status=status.HTTP_401_UNAUTHORIZED)
            if not is_verified(user):
                return Response({"detail": "请先完成账号认证后再投票。"}, status=status.HTTP_403_FORBIDDEN)
        try:
            voting.cast_ballot(
                activity=activity,
                user=user,
                option_ids=request.data.get("option_ids") or [],
                ip_address=client_ip_from_request(request),
                device_id=device_id_from_request(request),
            )
        except voting.BallotError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_400_BAD_REQUEST)
        return self._serialized(activity, request)

    # ── 调研作答（公开受众任何人；仅成员须登录；已登录一人一次；访客按设备一次）──
    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        activity = self.get_object()
        if status_of(activity) not in (None, Review.STATUS_APPROVED):
            return Response({"detail": "调研尚未公开"}, status=status.HTTP_400_BAD_REQUEST)
        if not can_respond(activity, request.user):
            if activity.type != "survey":
                return Response({"detail": "仅调研可以作答"}, status=status.HTTP_400_BAD_REQUEST)
            if activity.status != OPEN:
                return Response({"detail": "当前不可作答"}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"detail": "仅成员可作答，请先登录"}, status=status.HTTP_401_UNAUTHORIZED)
        answers = request.data.get("answers")
        if not isinstance(answers, dict):
            return Response({"detail": "answers 须为 JSON 对象"}, status=status.HTTP_400_BAD_REQUEST)
        questionnaire = activity.questionnaire
        if questionnaire is None:
            return Response({"detail": "问卷不存在"}, status=status.HTTP_400_BAD_REQUEST)
        user = request.user if request.user.is_authenticated else None
        device_id = device_id_from_request(request)
        if user is None:
            if not device_id:
                return Response({"detail": "缺少设备标识"}, status=status.HTTP_400_BAD_REQUEST)
            if QuestionnaireResponse.objects.filter(
                questionnaire=questionnaire, user__isnull=True, device_id=device_id,
            ).exists():
                return Response({"detail": "你已经提交过了"}, status=status.HTTP_400_BAD_REQUEST)
        elif QuestionnaireResponse.objects.filter(
            questionnaire=questionnaire, user=user,
        ).exists():
            return Response({"detail": "你已经提交过了"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                QuestionnaireResponse.objects.create(
                    questionnaire=questionnaire, user=user,
                    device_id=device_id if user is None else "",
                    answers=answers,
                )
        except IntegrityError:
            return Response({"detail": "你已经提交过了"}, status=status.HTTP_400_BAD_REQUEST)
        activity = self.get_queryset().get(pk=activity.pk)
        return Response(
            ActivityDetailSerializer(activity, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ── 问卷作答查看（发起人 / manage_activity → 全部；其他登录用户 → 自己的）──
    @action(detail=True, methods=["get"], url_path="responses")
    def responses(self, request, pk=None):
        activity = self.get_object()
        if activity.type != "survey":
            return Response({"detail": "仅调研有问卷作答"}, status=status.HTTP_400_BAD_REQUEST)
        questionnaire = activity.questionnaire
        if questionnaire is None:
            return Response({"detail": "问卷不存在"}, status=status.HTTP_400_BAD_REQUEST)
        user = request.user
        is_manager = activity.creator_id == user.pk or user.has_perm("activities.manage_activity")
        rows = (
            questionnaire.responses.select_related("user").all()
            if is_manager
            else questionnaire.responses.filter(user=user)
        )
        # 检索作答内容（?q=）：口径与实现见 activities/survey_search.py——
        # JSONField 跨库无法可靠地做中文模糊匹配，故在 Python 侧逐行扫描；
        # 本端点本来就要把整份作答下发，扫描不额外增加查询。
        query = survey_search.clean_query(request.query_params.get("q"))
        rows = list(rows)
        results = []
        for row in rows:
            answers = row.answers or {}
            if query:
                matched, matches = survey_search.search_answers(questionnaire.schema, answers, query)
                if not matched:
                    continue
            else:
                matches = []
            results.append({
                "id": row.pk,
                "user_label": (
                    row.user.username if row.user_id
                    else (f"访客 · {row.device_id[:8]}" if row.device_id else "访客")
                ),
                "answers": answers,
                "submitted_at": row.submitted_at,
                "matches": matches,
            })
        return Response({
            "schema": questionnaire.schema,
            "is_manager": is_manager,
            # total 是「未过滤的可见份数」，供前端显示「匹配 N / 共 M」
            "total": len(rows),
            "query": query,
            "results": results,
        })

    # ── 征集投稿（一次性多文件、提交即锁定、一人一作品）──
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        activity = self.get_object()
        if not can_submit(activity, request.user):
            if activity.type != "collection":
                return Response({"detail": "仅征集可以投稿"}, status=status.HTTP_400_BAD_REQUEST)
            # 用 accepting_submissions 而非落库 status：征集过期时 status 可能仍是
            # collecting（快照滞后），照 status 判会给出错误文案「当前不可投稿」。
            if not accepting_submissions(activity):
                return Response({"detail": "征集已结束收件"}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"detail": "当前不可投稿"}, status=status.HTTP_400_BAD_REQUEST)
        if Submission.objects.filter(activity=activity, submitter=request.user).exists():
            return Response({"detail": "你已经提交过作品了（一人一作品）"}, status=status.HTTP_400_BAD_REQUEST)

        files = request.FILES.getlist("files")
        if not files:
            return Response({"detail": "请至少上传一个文件"}, status=status.HTTP_400_BAD_REQUEST)
        if len(files) > activity.max_files_per_submission:
            return Response(
                {"detail": f"单个作品最多 {activity.max_files_per_submission} 个文件"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        allowed = _parse_extensions(activity.allowed_extensions)

        def extra_validate(f):
            if activity.max_file_size and f.size > activity.max_file_size:
                return f"文件「{f.name}」超过征集规定的单文件大小上限"
            if allowed:
                ext = os.path.splitext(f.name)[1].lower()
                if ext not in allowed:
                    return f"文件「{f.name}」的后缀不在允许范围"
            return None

        for f in files:
            err = upload_error(f)  # 全局禁用扩展名 + 同步上传上限
            if err:
                return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
            err = extra_validate(f)
            if err:
                return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            submission = Submission.objects.create(activity=activity, submitter=request.user)
            for f in files:
                create_attachment(
                    user=request.user, parent=submission, file=f,
                    extra_validate=extra_validate,
                )
            maybe_close_collection_on_cap(activity)  # 满额自动 collecting→reviewing

        return self._serialized(activity, request, status.HTTP_201_CREATED)

    # ── 征集复审（录用/退稿；collecting 与 reviewing 阶段均可滚动复审）──
    @action(detail=True, methods=["post"], url_path="review_submission")
    def review_submission(self, request, pk=None):
        activity = self.get_object()
        if activity.type != "collection":
            return Response({"detail": "仅征集作品可复审"}, status=status.HTTP_400_BAD_REQUEST)
        if not activity.review_enabled:
            return Response({"detail": "本征集未启用复审"}, status=status.HTTP_400_BAD_REQUEST)
        if activity.status not in (COLLECTING, REVIEWING):
            return Response({"detail": "当前不可复审"}, status=status.HTTP_400_BAD_REQUEST)
        decision = request.data.get("decision")
        if decision not in ("accepted", "rejected"):
            return Response(
                {"detail": "decision 须为 accepted 或 rejected"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        comment = (request.data.get("comment") or "").strip()
        try:
            submission = activity.submissions.get(pk=request.data.get("submission_id"))
        except (Submission.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "作品不存在"}, status=status.HTTP_404_NOT_FOUND)
        submission.review_status = decision
        submission.moderation_note = comment
        submission.moderated_by = request.user
        submission.moderated_at = timezone.now()
        submission.save(update_fields=[
            "review_status", "moderation_note", "moderated_by", "moderated_at",
        ])
        activity = self.get_queryset().get(pk=activity.pk)
        return Response(ActivityDetailSerializer(activity, context={"request": request}).data)

    # ── 提前关闭（众议立即结算 / 征集结束收件进入复审）──
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        activity = self.get_object()
        if activity.type not in ("deliberation", "exhibition", "survey", "collection"):
            return Response({"detail": "不支持"}, status=status.HTTP_400_BAD_REQUEST)
        if not can_close(activity, request.user):
            return Response({"detail": "当前不可关闭"}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        if activity.type == "collection":
            Activity.objects.filter(pk=activity.pk, status=COLLECTING).update(
                status=collection_close_target(activity), updated_at=now,
            )
        else:
            Activity.objects.filter(pk=activity.pk, status=OPEN).update(
                status=CLOSED, updated_at=now,
            )
        return self._serialized(activity, request)

    # ── 展示:详情页布展(待开始/展示中加/删/导入;改标题限待开始)──
    @action(detail=True, methods=["post"], url_path="add_exhibit")
    def add_exhibit(self, request, pk=None):
        activity = self.get_object()
        try:
            exhibition.create_exhibit(
                activity=activity, user=request.user,
                title=(request.data.get("title") or "").strip(),
                files=request.FILES.getlist("files"),
            )
        except exhibition.ExhibitionError as exc:
            return Response({"detail": exc.detail}, status=exc.http_status)
        return self._serialized(activity, request)

    @action(detail=True, methods=["post"], url_path="delete_exhibit")
    def delete_exhibit(self, request, pk=None):
        activity = self.get_object()
        try:
            exhibition.delete_exhibit(
                activity=activity, user=request.user,
                exhibit_id=request.data.get("exhibit_id"),
            )
        except exhibition.ExhibitionError as exc:
            return Response({"detail": exc.detail}, status=exc.http_status)
        return self._serialized(activity, request)

    @action(detail=True, methods=["post"], url_path="update_exhibit")
    def update_exhibit(self, request, pk=None):
        activity = self.get_object()
        try:
            exhibition.update_exhibit(
                activity=activity, user=request.user,
                exhibit_id=request.data.get("exhibit_id"),
                title=request.data.get("title"),
                files=request.FILES.getlist("files"),
            )
        except exhibition.ExhibitionError as exc:
            return Response({"detail": exc.detail}, status=exc.http_status)
        return self._serialized(activity, request)

    @action(detail=True, methods=["post"], url_path="import_from_collection")
    def import_from_collection(self, request, pk=None):
        activity = self.get_object()
        try:
            exhibition.import_submissions(
                activity=activity, user=request.user,
                collection_id=request.data.get("collection_id"),
                submission_ids=request.data.get("submission_ids") or [],
            )
        except exhibition.ExhibitionError as exc:
            return Response({"detail": exc.detail}, status=exc.http_status)
        return self._serialized(activity, request)

    # ── 展示：点赞 / 点踩（三态切换：none/like/dislike）──
    @action(detail=True, methods=["post"], url_path="rate")
    def rate(self, request, pk=None):
        activity = self.get_object()
        # 守卫（类型=展示、状态=open）统一走 lifecycle.can_rate，与 vote/submit 同模式
        if not can_rate(activity, request.user):
            return Response({"detail": "当前不可评分（展示未开放或已结束）"}, status=status.HTTP_400_BAD_REQUEST)
        choice = request.data.get("choice")
        if choice not in ("like", "dislike"):
            return Response({"detail": "choice 须为 like 或 dislike"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            exhibit = activity.exhibits.get(pk=request.data.get("exhibit_id"))
        except (Exhibit.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "展品不存在"}, status=status.HTTP_404_NOT_FOUND)
        existing = ExhibitRating.objects.filter(exhibit=exhibit, user=request.user).first()
        if existing and existing.choice == choice:
            existing.delete()  # 再点当前态 → none
        elif existing:
            existing.choice = choice
            existing.save(update_fields=["choice"])
        else:
            ExhibitRating.objects.create(exhibit=exhibit, user=request.user, choice=choice)
        activity = self.get_queryset().get(pk=activity.pk)
        return Response(ActivityDetailSerializer(activity, context={"request": request}).data)

    @action(detail=False, methods=["post"], url_path="upload_image")
    def upload_image(self, request):
        """正文内嵌图片上传（已认证成员）：返回 {url}。供编辑器「插入图片」与 Word 导入共用。"""
        file = request.FILES.get("image")
        if not file:
            return Response({"detail": "请选择图片。"}, status=status.HTTP_400_BAD_REQUEST)
        if file.size > _CONTENT_IMAGE_MAX_SIZE:
            return Response({"detail": "图片不能超过 5MB。"}, status=status.HTTP_400_BAD_REQUEST)
        if file.content_type not in _CONTENT_IMAGE_TYPES:
            return Response(
                {"detail": "仅支持 JPG、PNG、GIF、WebP 格式。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        path = default_storage.save(_content_image_path(file.name), file)
        return Response({"url": request.build_absolute_uri(default_storage.url(path))})

    @action(detail=False, methods=["post"], url_path="survey_upload")
    def survey_upload(self, request):
        """问卷文件题上传（填答者，含游客）：返回 {url}。仅图片（JPG/PNG/GIF/WebP）或 PDF。"""
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "请选择文件。"}, status=status.HTTP_400_BAD_REQUEST)
        err = upload_error(file)  # 站点同步上限 + 禁止扩展名
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        if file.content_type not in _SURVEY_UPLOAD_TYPES:
            return Response(
                {"detail": "仅支持图片（JPG / PNG / GIF / WebP）或 PDF。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        path = default_storage.save(_survey_upload_path(file.name), file)
        return Response({"url": request.build_absolute_uri(default_storage.url(path))})
