from rest_framework import serializers

from tasks.serializers import SimpleUserSerializer

from reviews.visibility import comment_for, status_of

from .models import Tutorial

_VIDEO_TYPES = {"video/mp4", "video/webm", "video/ogg", "video/quicktime"}
_DOC_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
_MAX_BYTES = 500 * 1024 * 1024


class TutorialListSerializer(serializers.ModelSerializer):
    uploader = SimpleUserSerializer(read_only=True)
    cover_url = serializers.SerializerMethodField()
    favorite_count = serializers.SerializerMethodField()
    review_status = serializers.SerializerMethodField()
    favorited = serializers.SerializerMethodField()

    class Meta:
        model = Tutorial
        fields = [
            "id", "title", "description", "file_type", "file_name", "file_size",
            "cover_url", "uploader", "views", "favorite_count",
            "favorited", "review_status", "created_at",
        ]
        # file_* 与 views 由服务端在校验 / 播报时写入，不接受客户端回填。
        read_only_fields = ["file_type", "file_name", "file_size", "views"]

    def get_cover_url(self, obj):
        if not obj.cover:
            return None
        request = self.context.get("request")
        url = obj.cover.url
        return request.build_absolute_uri(url) if request else url

    def get_favorite_count(self, obj):
        return obj.favorites.count()

    def get_review_status(self, obj):
        return status_of(obj)

    def get_favorited(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        return obj.favorites.filter(user=user).exists()


class TutorialDetailSerializer(TutorialListSerializer):
    file_url = serializers.SerializerMethodField()
    review_comment = serializers.SerializerMethodField()

    class Meta(TutorialListSerializer.Meta):
        fields = TutorialListSerializer.Meta.fields + ["file_url", "review_comment", "updated_at"]

    def get_file_url(self, obj):
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url

    def get_review_comment(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return comment_for(obj, user)


def classify_tutorial_file(upload):
    content_type = getattr(upload, "content_type", "") or ""
    name = (upload.name or "").lower()
    if content_type in _VIDEO_TYPES or name.endswith((".mp4", ".webm", ".ogv", ".mov")):
        return Tutorial.FILE_VIDEO
    if content_type in _DOC_TYPES or name.endswith((".pdf", ".docx", ".doc")):
        return Tutorial.FILE_DOCUMENT
    raise serializers.ValidationError({"file": "仅支持视频（mp4/webm）或文档（pdf/docx）"})


def validate_tutorial_upload(upload):
    if upload.size > _MAX_BYTES:
        raise serializers.ValidationError({"file": "文件不能超过 500MB"})
    return classify_tutorial_file(upload)
