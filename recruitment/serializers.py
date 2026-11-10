from rest_framework import serializers

from activities.models import Questionnaire, QuestionnaireResponse
from common.rich_text import sanitize_html
from common.survey_schema import InvalidSurveySchema, validate_schema_dict

from .models import RecruitmentNotice


class RecruitmentNoticeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitmentNotice
        fields = ["content", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_content(self, value):
        return sanitize_html(value or "")


class JoinQuestionnaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = Questionnaire
        fields = ["schema", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_schema(self, value):
        try:
            return validate_schema_dict(value)
        except InvalidSurveySchema as e:
            raise serializers.ValidationError(str(e))


class JoinResponseSerializer(serializers.ModelSerializer):
    notice_acknowledged = serializers.BooleanField(write_only=True)

    class Meta:
        model = QuestionnaireResponse
        fields = ["id", "answers", "notice_acknowledged", "submitted_at"]
        read_only_fields = ["id", "submitted_at"]

    def validate_notice_acknowledged(self, value):
        if not value:
            raise serializers.ValidationError("请先勾选「我已阅读并知晓公告内容」")
        return value

    def validate_answers(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("请填写问卷后再提交")
        return value

    def create(self, validated_data):
        validated_data.pop("notice_acknowledged", None)
        return super().create(validated_data)
