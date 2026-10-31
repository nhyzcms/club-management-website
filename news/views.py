import hashlib
import os
import uuid

from django.core.files.storage import default_storage
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import MemberIdentity
from accounts.utils import get_client_ip
from messaging.services import thread_for
from reviews.lifecycle import open_review, reopen_on_edit
from reviews.visibility import public_q, visible_queryset
from common.models import Tag

from .models import (
    COVER_ALLOWED_TYPES, COVER_MAX_SIZE, News, NewsDraft, NewsView,
    cover_upload_path,
)
from .permissions import CanManageNews, CanManageNewsDraft
from .serializers import NewsDetailSerializer, NewsDraftSerializer, NewsListSerializer, NewsTagSerializer
from .feed import build_feed

# 公开（匿名可访问）的 action
PUBLIC_ACTIONS = frozenset({"list", "retrieve", "featured", "hot", "tags", "overview", "feed"})

# 正文内嵌图片上限（文章配图，比 2MB 头像略宽）
_CONTENT_IMAGE_MAX_SIZE = 5 * 1024 * 1024
_CONTENT_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def _content_image_path(filename):
    ext = os.path.splitext(filename)[1]
    return f"news_content_images/{uuid.uuid4().hex}{ext}"


class NewsViewSet(viewsets.ModelViewSet):
    """新闻：公开读（已发布），有 news 写权限者（信息组）可写。"""

    filterset_fields = ["featured", "is_published"]
    search_fields = ["title", "summary", "content"]
    ordering_fields = ["published_at", "views", "created_at"]
    ordering = ["-published_at"]

    def get_queryset(self): # pyright: ignore[reportIncompatibleMethodOverride]
        qs = News.objects.select_related(
            "author", "author__profile", "review",
        ).prefetch_related("tags")
        user = self.request.user
        if self.action == "mine":
            if not user.is_authenticated:
                return qs.none()
            return qs.filter(author=user)
        # 审核轴走 visible_queryset；is_published 是新闻生命周期，在公开支相交。
        if self.action in PUBLIC_ACTIONS:
            vis_action = "retrieve" if self.action == "retrieve" else "list"
            visible = visible_queryset(qs, user, "news", action=vis_action)
            if self.action == "retrieve":
                if not user.is_authenticated:
                    return visible.filter(is_published=True)
                if user.has_perm("reviews.moderate"):
                    return visible
                return visible.filter(Q(is_published=True) | Q(author=user))
            return visible.filter(is_published=True)
        return qs

    def get_serializer_class(self): # type: ignore
        if self.action in ("list", "mine"):
            return NewsListSerializer
        return NewsDetailSerializer

    def get_permissions(self):
        # 公开读（GET：list/retrieve/featured/hot/tags）匿名可读；
        # 写（POST/PUT/PATCH/DELETE：create/update/destroy/upload_image）须持 news.manage_news。
        if self.action == "mine":
            return [IsAuthenticated()]
        if self.action == "draft":
            # 草稿区（自动保存）：读 / 存 / 弃都须 news.manage_news——含未发布内容，不放行匿名读
            return [CanManageNewsDraft()]
        return [CanManageNews()]

    def perform_create(self, serializer):
        news = serializer.save(author=self.request.user)
        open_review(news=news, actor=self.request.user)
        thread_for(news)

    # 会改变「已过审版本」的实质字段。featured（头条位）/ is_published（发布开关）
    # 不改内容，不重新入审。
    _CONTENT_FIELDS = {"title", "summary", "content", "cover_image", "cover_image_ref", "tags"}

    def perform_update(self, serializer):
        incoming = set(serializer.validated_data)
        news = serializer.save()
        if incoming & self._CONTENT_FIELDS and reopen_on_edit(news=news, actor=self.request.user):
            # 序列化器可能已缓存旧 review 关系；清掉缓存，让响应反映 pending。
            news.refresh_from_db()

    @action(detail=False, methods=["get"])
    def mine(self, request):
        """作者预览：当前用户的全部新闻（含待审/驳回/下架），不分公开过滤。"""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = NewsListSerializer(page or queryset, many=True, context={"request": request})
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="upload_image")
    def upload_image(self, request):
        """正文内嵌图片上传（仅信息组）：返回 {url}。
        供编辑器「插入图片」与 Word 导入时的内嵌图片共同使用。"""
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

    @action(detail=False, methods=["post"], url_path="upload_cover")
    def upload_cover(self, request):
        """封面预上传（编辑页「选完即传」）：校验后存 news_covers/，返回 {url}。

        保存稿件时以 ``cover_image_ref`` 字段引用返回的 url 完成挂载——
        避免把文件捆在保存请求里（部分移动端浏览器对「带文件的 PATCH」不稳定）。
        """
        file = request.FILES.get("image")
        if not file:
            return Response({"detail": "请选择图片。"}, status=status.HTTP_400_BAD_REQUEST)
        if file.size > COVER_MAX_SIZE:
            return Response({"detail": "封面图不能超过 5MB。"}, status=status.HTTP_400_BAD_REQUEST)
        if file.content_type not in COVER_ALLOWED_TYPES:
            return Response(
                {"detail": "封面仅支持 JPG、PNG、GIF、WebP 格式。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        path = default_storage.save(cover_upload_path(None, file.name), file)
        return Response({"url": request.build_absolute_uri(default_storage.url(path))})

    @action(detail=True, methods=["get", "post", "delete"], url_path="draft")
    def draft(self, request, pk=None):
        """服务端草稿区（编辑页自动保存）。

        - GET：读草稿——仅「已发布且存过草稿」返回内容，否则 ``{"draft": None}``；
        - POST：保存——已发布新闻写 draft_* 暂存区（公开页保持旧版，直到「保存修改」上线）；
          未发布新闻直接写正文（稿件本体即草稿，列表可见）；
        - DELETE：放弃修改（清空已发布新闻的草稿区）。
        """
        news = self.get_object()

        if request.method == "GET":
            if not news.is_published or not news.draft_saved_at:
                return Response({"draft": None})
            return Response({"draft": {
                "title": news.draft_title,
                "summary": news.draft_summary,
                "content": news.draft_content,
                "saved_at": news.draft_saved_at,
            }})

        if request.method == "DELETE":
            # 放弃修改 = 删掉草稿行（B7 起草稿在独立表）
            NewsDraft.objects.filter(news=news).delete()
            return Response({"draft": None})

        serializer = NewsDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if news.is_published:
            defaults = {}
            if "title" in data:
                defaults["title"] = data["title"]
            if "summary" in data:
                defaults["summary"] = data["summary"]
            if "content" in data:
                defaults["content"] = data["content"]
            saved_at = timezone.now()
            draft = NewsDraft.objects.filter(news=news).first()
            if draft is None:
                # 首存：缺省字段留空（与原「只写传了的字段」语义一致）
                NewsDraft.objects.create(news=news, saved_at=saved_at, **defaults)
            else:
                for field, value in defaults.items():
                    setattr(draft, field, value)
                draft.saved_at = saved_at
                draft.save(update_fields=[*defaults.keys(), "saved_at"])
            return Response({"saved_at": saved_at, "is_draft": True})

        # 未发布：直接写正文；空标题不覆盖（避免「我的稿件」出现空标题行）
        if data.get("title", "").strip():
            news.title = data["title"]
        if "summary" in data:
            news.summary = data["summary"]
        if "content" in data:
            news.content = data["content"]
        news.save(update_fields=["title", "summary", "content", "updated_at"])
        return Response({"saved_at": timezone.now(), "is_draft": False})

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # 去重阅读计数：登录用户按 user、匿名按 IP 的 sha256 去重；仅新读者才 +1。
        if request.user.is_authenticated:
            reader_key = f"user:{request.user.pk}"
        else:
            ip = get_client_ip(request) or ""
            reader_key = "ip:" + hashlib.sha256(ip.encode()).hexdigest()
        _, created = NewsView.objects.get_or_create(news=instance, reader_key=reader_key)
        if created:
            News.objects.filter(pk=instance.pk).update(views=F("views") + 1)
            instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def featured(self, request):
        """头条：**只认手工置顶（featured=True）**；没有置顶就返回 null。

        早期实现会在无置顶时退化为「阅读人数最高」，导致从未设为头条的普通新闻
        被前端打上「头条」徽标——这正是要修的展示错误，不要再加回退化分支。
        """
        item = (
            self.get_queryset()
            .filter(featured=True)
            .order_by("-published_at", "-created_at")
            .first()
        )
        if item is None:
            return Response(None)
        return Response(NewsListSerializer(item, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def hot(self, request):
        """热门阅读：按阅读量前 5。"""
        qs = self.get_queryset().order_by("-views", "-published_at")[:5]
        return Response(NewsListSerializer(qs, many=True, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def tags(self, request):
        """标签云：仅返回被新闻引用过的标签，附新闻数。"""
        qs = Tag.objects.filter(
            news__in=News.objects.filter(public_q("news"), is_published=True),
        ).distinct()
        return Response(NewsTagSerializer(qs, many=True, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def overview(self, request):
        """社团概览：成员=已分配社员编号数，作品=已发布新闻数。匿名可读。

        成员数取社员名册行数（``MemberIdentity`` = 一人一个编号，ADR-0025），
        不再取活跃账号数：名册导入即计入，与本人是否注册账号、账号是否仍活跃无关。
        """
        return Response({
            "members": MemberIdentity.objects.count(),
            "works": News.objects.filter(public_q("news"), is_published=True).count(),
        })

    @action(detail=False, methods=["get"])
    def feed(self, request):
        """首页「社团动态」聚合：头条新闻 + 混排活动/新闻/(登录时的)任务。匿名可读。"""
        try:
            limit = int(request.query_params.get("limit", 6))
        except (TypeError, ValueError):
            limit = 6
        return Response(build_feed(request=request, limit=limit))
