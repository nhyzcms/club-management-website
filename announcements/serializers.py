"""全站弹窗公告的对外契约（前端 ``types/announcements.ts`` 与此一一对应）。"""
from rest_framework import serializers

from .models import Announcement
from .services import read_map


class AnnouncementSerializer(serializers.ModelSerializer):
    audience_label = serializers.CharField(source="get_audience_display", read_only=True)
    has_document = serializers.BooleanField(read_only=True)
    file_url = serializers.SerializerMethodField()
    read_at = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = [
            "id",
            "title",
            "summary",
            "audience",
            "audience_label",
            "has_document",
            "document_kind",
            "document_name",
            "document_size",
            "file_url",
            "published_at",
            "expires_at",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj) -> str | None:
        """走鉴权端点（不暴露 /media/ 直链：受众=管理员的公告不能被匿名拿到）。"""
        if not obj.has_document:
            return None
        return f"/announcements/{obj.pk}/file/"

    def get_read_at(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        reads = self.context.get("read_map")
        if reads is None:
            reads = read_map(obj)
        value = reads.get(user.pk)
        return value.isoformat() if value else None
