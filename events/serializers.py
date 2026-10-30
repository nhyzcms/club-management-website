"""活动序列化（读写同一套字段；状态与组织者只读）。"""
from rest_framework import serializers

from common.rich_text import sanitize_html
from tasks.serializers import SimpleUserSerializer

from .models import Event


class EventSerializer(serializers.ModelSerializer):
    organizer = SimpleUserSerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    visibility_label = serializers.CharField(source="get_visibility_display", read_only=True)

    class Meta:
        model = Event
        fields = [
            "id", "title", "summary", "body",
            "organizer", "start_at", "end_at",
            "status", "status_label", "visibility", "visibility_label",
            "module_key", "created_at", "updated_at",
        ]
        read_only_fields = ["status", "organizer", "created_at", "updated_at"]

    def validate_body(self, value):
        """正文按全站统一规则清洗（与新闻/互动/教程一致，防存储型 XSS）。"""
        return sanitize_html(value or "")

    def validate(self, attrs):
        start_at = attrs.get("start_at", getattr(self.instance, "start_at", None))
        end_at = attrs.get("end_at", getattr(self.instance, "end_at", None))
        if end_at is not None and start_at is not None and end_at <= start_at:
            raise serializers.ValidationError({"end_at": "结束时间必须晚于开始时间"})
        return attrs
