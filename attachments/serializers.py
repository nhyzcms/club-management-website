from rest_framework import serializers

from .models import Attachment


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id", "file_url", "file_type", "file_name",
            "file_size", "uploaded_by", "uploaded_at",
        ]

    def get_uploaded_by(self, obj):
        # 延迟导入打破 tasks ↔ attachments 的序列化器循环：
        # 各父级详情序列化器复用本类，而 SimpleUserSerializer 住在
        # tasks.serializers——若在模块顶层导入会成环。运行期再取，Python 已缓存模块。
        from tasks.serializers import SimpleUserSerializer

        return SimpleUserSerializer(obj.uploaded_by, context=self.context).data

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and hasattr(obj.file, "url"):
            url = obj.file.url
            return request.build_absolute_uri(url) if request else url
        return None
