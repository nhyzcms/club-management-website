"""全站弹窗公告的读取端点（发布 / 编辑 / 统计都在 Django 后台）。

- ``GET  /announcements/active/``    当前用户还没读过的在线公告（匿名只看全站受众）
- ``GET  /announcements/<id>/``      详情（站内通知点击回看；同样按受众鉴权）
- ``POST /announcements/<id>/read/`` 记已读（幂等）
- ``GET  /announcements/<id>/file/`` 文档原件（鉴权后 inline 输出，不走 /media/ 直链）
"""
import mimetypes

from django.http import FileResponse, Http404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Announcement
from .serializers import AnnouncementSerializer
from .services import active_for, can_see, mark_read


class ActiveAnnouncementsView(APIView):
    """``GET /announcements/active/``：一次最多 5 条，前端逐条弹。"""

    permission_classes = [AllowAny]

    def get(self, request):
        rows = active_for(request.user)
        data = AnnouncementSerializer(
            rows, many=True, context={"request": request},
        ).data
        return Response({"count": len(rows), "results": data})


class AnnouncementDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk: int):
        row = Announcement.objects.filter(pk=pk).first()
        if row is None or not can_see(request.user, row):
            raise Http404("公告不存在或已下线")
        return Response(
            AnnouncementSerializer(row, context={"request": request}).data
        )


class AnnouncementReadView(APIView):
    """``POST /announcements/<id>/read/``：关闭弹窗即写台账（重复调用不报错）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        row = Announcement.objects.filter(pk=pk).first()
        if row is None or not can_see(request.user, row):
            raise Http404("公告不存在或已下线")
        record, created = mark_read(row, request.user)
        return Response({
            "read_at": record.read_at.isoformat(),
            "already_read": not created,
        })


def announcement_file_view(request, pk: int):
    """鉴权后输出原件。PDF 用 ``application/pdf`` inline，浏览器 / pdf.js 都能直接取。"""
    row = Announcement.objects.filter(pk=pk).first()
    if row is None or not can_see(request.user, row):
        raise Http404("公告不存在或已下线")
    if not row.document or not row.document.storage.exists(row.document.name):
        raise Http404("文档不存在")

    guess, _ = mimetypes.guess_type(row.document.name)
    content_type = guess or (
        "application/pdf" if row.document_kind == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    response = FileResponse(
        row.document.open("rb"),
        content_type=content_type,
        as_attachment=False,
        filename=row.document_name or None,
    )
    response["X-Content-Type-Options"] = "nosniff"
    # 鉴权资源：只允许私有缓存，避免中间代理把「管理员公告」缓存给其他人。
    response["Cache-Control"] = "private, max-age=60"
    return response
