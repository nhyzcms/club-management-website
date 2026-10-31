from rest_framework import serializers

from common.rich_text import sanitize_html
from common.uploads import extension_of, sniff_pdf, sniff_zip

from .models import AboutBlock, AboutPage

_DOC_MAX_BYTES = 20 * 1024 * 1024


class AboutBlockSerializer(serializers.ModelSerializer):
    document_url = serializers.SerializerMethodField()
    document_name = serializers.SerializerMethodField()

    class Meta:
        model = AboutBlock
        fields = [
            "key", "title", "content", "order", "panorama_url",
            "document_url", "document_name", "updated_at",
        ]
        read_only_fields = ["key", "order", "document_url", "document_name", "updated_at"]

    def get_document_url(self, obj):
        if not obj.document:
            return None
        request = self.context.get("request")
        url = obj.document.url
        return request.build_absolute_uri(url) if request else url

    def get_document_name(self, obj):
        if not obj.document:
            return ""
        return obj.document.name.rsplit("/", 1)[-1]

    def validate_content(self, value):
        return sanitize_html(value or "")

    def validate_panorama_url(self, value):
        value = (value or "").strip()
        if value and not (value.startswith("https://") or value.startswith("http://")):
            raise serializers.ValidationError("全景图外链须为 http(s) URL")
        return value


class AboutOverviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = AboutPage
        fields = ["founded", "advisor", "intro", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_founded(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("请填写成立时间")
        if len(value) > 40:
            raise serializers.ValidationError("成立时间过长")
        return value

    def validate_advisor(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("请填写指导")
        if len(value) > 80:
            raise serializers.ValidationError("指导过长")
        return value

    def validate_intro(self, value):
        return (value or "").strip()[:200]


class AboutPageSerializer(serializers.Serializer):
    """公开聚合：全部区块 + 社团概览静态行。"""

    blocks = AboutBlockSerializer(many=True)
    overview = AboutOverviewSerializer()
    updated_at = serializers.DateTimeField()


def validate_about_document(file):
    """PDF / .docx 文档附件：大小 + **真实内容**（PDF 验 %PDF-、docx 验 ZIP 容器）。

    不再信任客户端声明的 content_type —— 任何一个可伪造的字段都不该决定文件去向。
    """
    if file.size > _DOC_MAX_BYTES:
        raise serializers.ValidationError({"document": "文档不能超过 20MB"})
    ext = extension_of(file.name)
    if ext == ".pdf":
        if not sniff_pdf(file):
            raise serializers.ValidationError({"document": "文件不是有效的 PDF"})
        return
    if ext == ".docx":
        if not sniff_zip(file):
            raise serializers.ValidationError({"document": "文件不是有效的 .docx"})
        return
    raise serializers.ValidationError({"document": "仅支持 PDF 或 .docx"})
