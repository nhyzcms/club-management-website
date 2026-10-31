from django.core.exceptions import ValidationError
from rest_framework import serializers

from common.uploads import rename_upload, sniff_image_extension

from .models import Exam, ExamBatch, ExamErrata, ExamSubject

_ERRATA_MAX_SIZE = 5 * 1024 * 1024


def _absolute_image_url(obj, request):
    if obj.image and hasattr(obj.image, "url"):
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url
    return None


class ExamSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamSubject
        fields = ["id", "name", "exam_date", "start_time", "end_time", "sort_order"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("请填写科目名称")
        return value

    def validate(self, attrs):
        start = attrs.get("start_time")
        end = attrs.get("end_time")
        if start is not None and end is not None and end <= start:
            raise serializers.ValidationError("结束时间必须晚于开始时间")
        return attrs


class ExamBatchSerializer(serializers.ModelSerializer):
    subjects = ExamSubjectSerializer(many=True)

    class Meta:
        model = ExamBatch
        fields = ["id", "name", "sort_order", "subjects"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("请填写批次名称")
        return value

    def validate_subjects(self, value):
        by_date: dict = {}
        for item in value:
            day = item["exam_date"]
            start, end = item["start_time"], item["end_time"]
            rows = by_date.setdefault(day, [])
            for other_start, other_end, other_name in rows:
                if start < other_end and end > other_start:
                    raise serializers.ValidationError(
                        f"{day}「{item['name']}」与「{other_name}」时间重叠"
                    )
            rows.append((start, end, item["name"]))
        return value


class ExamSerializer(serializers.ModelSerializer):
    batches = ExamBatchSerializer(many=True)

    class Meta:
        model = Exam
        fields = ["id", "title", "batches", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_title(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("请填写考试标题")
        return value

    def validate_batches(self, value):
        if not value:
            raise serializers.ValidationError("请至少添加一个批次")
        names = [b["name"] for b in value]
        if len(names) != len(set(names)):
            raise serializers.ValidationError("同一考试下批次名称不能重复")
        return value

    def create(self, validated_data):
        batches = validated_data.pop("batches")
        exam = Exam.objects.create(**validated_data)
        self._save_batches(exam, batches)
        return exam

    def update(self, instance, validated_data):
        batches = validated_data.pop("batches", None)
        instance.title = validated_data.get("title", instance.title)
        instance.save()
        if batches is not None:
            instance.batches.all().delete()
            self._save_batches(instance, batches)
        return instance

    def _save_batches(self, exam, batches):
        for batch_i, batch_data in enumerate(batches):
            subjects = batch_data["subjects"]
            batch = ExamBatch.objects.create(
                exam=exam,
                name=batch_data["name"],
                sort_order=batch_data.get("sort_order", batch_i),
            )
            ExamSubject.objects.bulk_create([
                ExamSubject(
                    batch=batch,
                    name=item["name"],
                    exam_date=item["exam_date"],
                    start_time=item["start_time"],
                    end_time=item["end_time"],
                    sort_order=item.get("sort_order", sub_i),
                )
                for sub_i, item in enumerate(subjects)
            ])


class ExamListSerializer(serializers.ModelSerializer):
    batch_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Exam
        fields = ["id", "title", "batch_count", "created_at", "updated_at"]


class ExamErrataSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    exam = serializers.PrimaryKeyRelatedField(queryset=Exam.objects.all())

    class Meta:
        model = ExamErrata
        fields = ["id", "exam", "text", "image", "image_url", "created_at", "expires_at"]
        read_only_fields = ["id", "image_url", "created_at", "expires_at"]
        extra_kwargs = {"image": {"write_only": True, "required": False}}

    def get_image_url(self, obj):
        return _absolute_image_url(obj, self.context.get("request"))

    def validate_text(self, value):
        return (value or "").strip()

    def validate_image(self, value):
        if value is None:
            return value
        if getattr(value, "size", 0) > _ERRATA_MAX_SIZE:
            raise serializers.ValidationError("图片不能超过 5MB")
        # content_type 是客户端声明、可伪造；用 Pillow 真实解码并让服务端决定扩展名。
        try:
            rename_upload(value, sniff_image_extension(value))
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages[0]) from exc
        return value

    def validate(self, attrs):
        text = attrs.get("text", "")
        image = attrs.get("image")
        if self.instance is None and not text and not image:
            raise serializers.ValidationError("请填写说明或上传图片")
        return attrs
