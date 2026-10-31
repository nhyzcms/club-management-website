from rest_framework import serializers

from tasks.serializers import SimpleUserSerializer

from common.uploads import extension_of
from reviews.visibility import comment_for, status_of

from .models import Tutorial

# 分类只看扩展名：客户端声明的 content_type 可以随便伪造，不能作为判据。
_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".ogv", ".mov"})
_DOC_EXTENSIONS = frozenset({".pdf", ".docx", ".doc"})
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
    """按**扩展名**分类（content_type 可伪造，不再作为判据）。"""
    ext = extension_of(upload.name)
    if ext in _VIDEO_EXTENSIONS:
        return Tutorial.FILE_VIDEO
    if ext in _DOC_EXTENSIONS:
        return Tutorial.FILE_DOCUMENT
    raise serializers.ValidationError({"file": "仅支持视频（mp4/webm）或文档（pdf/docx）"})


def validate_tutorial_upload(upload):
    if upload.size > _MAX_BYTES:
        raise serializers.ValidationError({"file": "文件不能超过 500MB"})
    return classify_tutorial_file(upload)
