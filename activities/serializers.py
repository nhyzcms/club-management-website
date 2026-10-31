from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from attachments.serializers import AttachmentSerializer
from common.rich_text import sanitize_html
from common.survey_schema import InvalidSurveySchema, validate_schema_dict
from reviews.visibility import comment_for, status_of
from tasks.serializers import CommentThreadHostMixin, SimpleUserSerializer  # 复用（与申报/新闻一致）

from .debt import owed_for
from .device import device_id_from_request
from .lifecycle import can_edit_schema, initial_status
from .models import (
    Activity,
    Ballot,
    Exhibit,
    Questionnaire,
    Submission,
    VoteOption,
    default_survey_schema,
)
from .voting import ballots_visible_to, options_locked, voting_active


class VoteOptionSerializer(serializers.ModelSerializer):
    """投票选项读侧：附各选项票数（聚合计数）。"""

    vote_count = serializers.SerializerMethodField()

    class Meta:
        model = VoteOption
        fields = ["id", "text", "order", "vote_count"]

    def get_vote_count(self, obj):
        return obj.selections.count()


class BallotSerializer(serializers.ModelSerializer):
    """公开选票：投票人 + 勾选的 option_ids。秘密投票下不输出（get_ballots 裁剪）。"""

    voter = SimpleUserSerializer(read_only=True)
    option_ids = serializers.SerializerMethodField()

    class Meta:
        model = Ballot
        fields = ["id", "voter", "option_ids", "created_at"]

    def get_option_ids(self, obj):
        return list(obj.selections.values_list("option_id", flat=True))


class SubmissionSerializer(serializers.ModelSerializer):
    """征集作品：提交者 + 一束文件 + 复审状态。"""

    submitter = SimpleUserSerializer(read_only=True)
    files = serializers.SerializerMethodField()
    # B2：模型字段已统一为 moderation_note / moderated_at，对外名保持不变
    review_comment = serializers.CharField(source="moderation_note", read_only=True)
    reviewed_at = serializers.DateTimeField(source="moderated_at", read_only=True)

    class Meta:
        model = Submission
        fields = [
            "id", "submitter", "files",
            "review_status", "review_comment", "reviewed_at", "created_at",
        ]

    def get_files(self, obj):
        return AttachmentSerializer(obj.attachments.all(), many=True, context=self.context).data


class ExhibitSerializer(serializers.ModelSerializer):
    """展品：标题 + 一束文件 + 投票计数 + 我的投票 + 赞/踩计数 + 我的评分。

    每个展品绑定一个 VoteOption（``vote_option``），投票计数即该 option 的票数。
    ``my_voted`` 在前端用 my_selections(option_ids) 推断，无需后端再算。
    """

    files = serializers.SerializerMethodField()
    vote_option_id = serializers.SerializerMethodField()
    vote_count = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    dislike_count = serializers.SerializerMethodField()
    my_rating = serializers.SerializerMethodField()

    class Meta:
        model = Exhibit
        fields = ["id", "title", "files", "vote_option_id", "vote_count",
                  "like_count", "dislike_count", "my_rating", "created_at"]

    def get_files(self, obj):
        return AttachmentSerializer(obj.attachments.all(), many=True, context=self.context).data

    def get_vote_option_id(self, obj):
        return obj.vote_option_id

    def get_vote_count(self, obj):
        # 经预取 exhibits__vote_option__selections 在内存计票，避免 N+1
        if not obj.vote_option_id:
            return 0
        return len(obj.vote_option.selections.all())

    def _ratings(self, obj):
        # 用预取缓存（exhibits__ratings）在内存算，避免 N+1
        return list(obj.ratings.all())

    def get_like_count(self, obj):
        return sum(1 for r in self._ratings(obj) if r.choice == "like")

    def get_dislike_count(self, obj):
        return sum(1 for r in self._ratings(obj) if r.choice == "dislike")

    def get_my_rating(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        for r in self._ratings(obj):
            if r.user_id == user.pk:
                return r.choice
        return None


class ActivityListSerializer(serializers.ModelSerializer):
    creator = SimpleUserSerializer(read_only=True)
    review_status = serializers.SerializerMethodField()
    owed = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            "id", "type", "status", "title", "creator",
            "audience",
            "review_status", "owed", "start_at", "end_at", "is_permanent",
            "created_at", "updated_at",
        ]

    def get_review_status(self, obj):
        return status_of(obj)

    def get_owed(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return owed_for(obj, user)


def _is_reviewer(activity, user):
    """征集复审者：活动发起人，或持 manage_activity / review_collection 权限者。

    review_collection 权限由 T5 落地；在此之前 has_perm 返回 False，复审者仅含发起人。
    """
    return user.is_authenticated and (
        activity.creator_id == user.pk
        or user.has_perm("activities.manage_activity")
        or user.has_perm("activities.review_collection")
    )


class ActivityDetailSerializer(CommentThreadHostMixin, serializers.ModelSerializer):
    creator = SimpleUserSerializer(read_only=True)
    review_status = serializers.SerializerMethodField()
    review_comment = serializers.SerializerMethodField()
    owed = serializers.SerializerMethodField()
    # 众议读侧（展示的"选项"即展品，走 exhibits，options 返回 None）
    options = serializers.SerializerMethodField()
    ballots = serializers.SerializerMethodField()
    my_selections = serializers.SerializerMethodField()
    total_ballots = serializers.SerializerMethodField()
    # 征集读侧
    my_submission = serializers.SerializerMethodField()
    submissions = serializers.SerializerMethodField()
    # 展示读侧
    exhibits = serializers.SerializerMethodField()
    # 调研读侧：问卷 + 我的作答 + 作答总数（不作答列表）+ Schema 可否改（生命周期，非权限）
    my_response = serializers.SerializerMethodField()
    response_count = serializers.SerializerMethodField()
    schema_editable = serializers.SerializerMethodField()
    schema = serializers.JSONField(required=False)
    # 众议写侧：创建时给选项文本（开放即锁定，无后续编辑）
    option_texts = serializers.ListField(
        child=serializers.CharField(max_length=200), write_only=True, required=False,
    )

    class Meta:
        model = Activity
        fields = [
            "id", "type", "status", "title", "body", "creator",
            "review_status", "review_comment", "owed",
            "start_at", "end_at", "is_permanent",
            "max_choices_per_voter", "is_secret_ballot",
            "allowed_extensions", "max_file_size", "max_files_per_submission", "max_submissions",
            "review_enabled", "voting_enabled",
            "audience", "schema", "my_response", "response_count", "schema_editable",
            "options", "ballots", "my_selections", "total_ballots",
            "my_submission", "submissions",
            "exhibits",
            "option_texts",
            "comment_thread", "comment_thread_status",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "creator", "status", "review_status", "review_comment", "owed",
            "my_response", "response_count", "schema_editable",
            "created_at", "updated_at",
        ]

    def get_review_status(self, obj):
        return status_of(obj)

    def get_review_comment(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return comment_for(obj, user)

    def get_owed(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return owed_for(obj, user)

    def validate_body(self, value):
        # 与新闻同级：写时消毒，存消毒后 HTML，读时原样返回。
        return sanitize_html(value or "")

    def validate_schema(self, value):
        try:
            return validate_schema_dict(value)
        except InvalidSurveySchema as e:
            raise serializers.ValidationError(str(e))

    def validate(self, attrs):
        # 受众创建后不可改（与展示 voting_enabled 同思路）
        if self.instance is not None and "audience" in attrs:
            if attrs["audience"] != self.instance.audience:
                raise serializers.ValidationError({"audience": "受众创建后不可改"})
        activity_type = attrs.get("type") or getattr(self.instance, "type", None)
        if activity_type != "survey":
            attrs.pop("schema", None)
        # 受众：调研=作答资格；众议/展示=投票资格（公开时游客可投）。征集无受众语义。
        if activity_type not in ("survey", "deliberation", "exhibition"):
            attrs.pop("audience", None)
        # 开始 < 截止（两者都给时；update 取实例现值兜底 partial）
        start_at = attrs.get("start_at", getattr(self.instance, "start_at", None))
        # 长期活动（不设截止）：is_permanent 与 end_at 二选一——
        # 勾选长期时拒绝同时给截止时间；由长期改回限期时必须补截止时间。
        permanent = attrs.get("is_permanent", getattr(self.instance, "is_permanent", False))
        if permanent:
            if attrs.get("end_at") is not None:
                raise serializers.ValidationError({"end_at": "已勾选「长期有效」，不能再设截止时间"})
            # 只在本次显式改 is_permanent 时清空既有截止，避免无关 partial 更新（如改评论开关）
            # 把 end_at 塞进 validated_data 而触发 perform_update 的「开放后锁定」守卫。
            if self.instance is not None and attrs.get("is_permanent") and self.instance.end_at is not None:
                attrs["end_at"] = None
        end_at = None if permanent else attrs.get("end_at", getattr(self.instance, "end_at", None))
        # 只在本次显式取消「长期」时索要截止时间；其余 partial 更新不受历史数据影响。
        if (
            not permanent
            and self.instance is not None
            and "is_permanent" in attrs
            and end_at is None
        ):
            raise serializers.ValidationError(
                {"end_at": "非长期活动须填写截止时间（不设截止请勾选「长期有效」）"}
            )
        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError({"start_at": "开始时间须早于截止时间"})
        # 众议选项与 K 值校验
        is_delib = attrs.get("type") == "deliberation" or (
            self.instance is not None and self.instance.type == "deliberation"
        )
        if is_delib:
            texts = attrs.get("option_texts")
            if self.instance is None:
                # 创建：必须给选项
                if not texts or len(texts) < 2:
                    raise serializers.ValidationError({"option_texts": "众议至少需要 2 个选项"})
            if texts is not None:  # 创建必给；更新（待开始）给了才校验
                if len(texts) > 50:
                    raise serializers.ValidationError({"option_texts": "众议选项不超过 50 个"})
                k = attrs.get("max_choices_per_voter", getattr(self.instance, "max_choices_per_voter", 1))
                if k < 1 or k > len(texts):
                    raise serializers.ValidationError(
                        {"max_choices_per_voter": "每人最多选几项须在 1..选项数 之间"}
                    )
        is_exhib = attrs.get("type") == "exhibition" or (
            self.instance is not None and self.instance.type == "exhibition"
        )
        if is_exhib and attrs.get("voting_enabled"):
            k = attrs.get("max_choices_per_voter", getattr(self.instance, "max_choices_per_voter", 1))
            if k < 1:
                raise serializers.ValidationError(
                    {"max_choices_per_voter": "每人最多选几项至少为 1"}
                )
        return attrs

    def create(self, validated_data):
        texts = validated_data.pop("option_texts", [])
        schema = validated_data.pop("schema", None)
        activity_type = validated_data["type"]
        # 截止默认相对开始时间：有 start_at 则从其起算，否则从现在；众议 +3 天 / 其余（含调研）+7 天。
        # 长期活动（is_permanent）不设截止，直接留空。
        start_at = validated_data.get("start_at")
        if validated_data.get("is_permanent"):
            validated_data["end_at"] = None
        elif not validated_data.get("end_at"):
            base = start_at or timezone.now()
            days = 3 if activity_type == "deliberation" else 7
            validated_data["end_at"] = base + timedelta(days=days)
        validated_data["status"] = initial_status(activity_type, start_at)
        activity = Activity.objects.create(**validated_data)
        if activity_type == "survey":
            # B8：问卷创建从 Activity.save() 搬到这儿。**必须排在设 schema 之前**
            # ——Activity.schema 的 setter 在没有 questionnaire_id 时静默 return，
            # 顺序反了会让调用方传的 schema 无声消失。
            questionnaire = Questionnaire.objects.create(
                kind=Questionnaire.KIND_SURVEY,
                schema=schema if schema is not None else default_survey_schema(),
            )
            Activity.objects.filter(pk=activity.pk).update(questionnaire=questionnaire)
            activity.questionnaire = questionnaire
        for i, text in enumerate(texts):
            VoteOption.objects.create(activity=activity, text=text, order=i)
        return self.apply_comment_thread_status(activity)

    def update(self, instance, validated_data):
        # 视图层 gate：标题/正文/时间须 scheduled；调研 schema 可在开放且零作答时改。
        texts = validated_data.pop("option_texts", None)
        schema = validated_data.pop("schema", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if schema is not None and instance.type == "survey":
            instance.schema = schema
        if texts is not None and instance.type == "deliberation":
            if options_locked(instance):
                raise serializers.ValidationError({"option_texts": "投票开放后选项已锁定"})
            instance.options.all().delete()
            for i, text in enumerate(texts):
                VoteOption.objects.create(activity=instance, text=text, order=i)
        return self.apply_comment_thread_status(instance)

    # ---- 众议读侧聚合 ----

    def get_options(self, obj):
        # 众议选项（附票数）；展示的选项即展品（见 exhibits），此处返回 None。
        if obj.type != "deliberation":
            return None
        return VoteOptionSerializer(obj.options.all(), many=True, context=self.context).data

    def get_ballots(self, obj):
        # 秘密投票：个人明细仅 is_superuser 可见；其余（含发起人）只见聚合计数。
        # 众议与展示（启用投票时）共用；纯陈列展示（voting_enabled=False）无投票数据。
        if not voting_active(obj):
            return None
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not ballots_visible_to(obj, user):
            return None
        return BallotSerializer(obj.ballots.all(), many=True, context=self.context).data

    def get_my_selections(self, obj):
        if not voting_active(obj):
            return None
        request = self.context.get("request")
        if request is None:
            return None
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            ballot = obj.ballots.filter(voter=user).first()
        else:
            # 公开受众的游客：按设备标识回显自己的票（与 get_my_response 同思路）
            device_id = device_id_from_request(request)
            if not device_id:
                return None
            ballot = obj.ballots.filter(voter__isnull=True, device_id=device_id).first()
        if ballot is None:
            return None
        return list(ballot.selections.values_list("option_id", flat=True))

    def get_total_ballots(self, obj):
        if not voting_active(obj):
            return None
        return obj.ballots.count()

    # ---- 征集读侧 ----

    def get_my_submission(self, obj):
        if obj.type != "collection":
            return None
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        sub = obj.submissions.filter(submitter=user).first()
        return SubmissionSerializer(sub, context=self.context).data if sub else None

    def get_submissions(self, obj):
        # 复审者见全部作品；其余只见录用作品（公开展示）。自己的作品另走 my_submission。
        # 关闭复审（review_enabled=False）时：全部作品对所有人公开（无录用门槛）。
        if obj.type != "collection":
            return None
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return []
        qs = obj.submissions.all()
        if obj.review_enabled and not _is_reviewer(obj, user):
            qs = qs.filter(review_status="accepted")
        return SubmissionSerializer(qs, many=True, context=self.context).data

    def get_exhibits(self, obj):
        # 展示读侧：全部展品（含文件、赞踩计数、我的评分）。非展示类型返回 None。
        if obj.type != "exhibition":
            return None
        return ExhibitSerializer(obj.exhibits.all(), many=True, context=self.context).data

    # ---- 调研读侧 ----

    def get_my_response(self, obj):
        if obj.type != "survey" or not obj.questionnaire_id:
            return None
        request = self.context.get("request")
        if request is None:
            return None
        user = getattr(request, "user", None)
        qs = obj.questionnaire.responses.all()
        if user and user.is_authenticated:
            resp = qs.filter(user=user).first()
        else:
            device_id = device_id_from_request(request)
            if not device_id:
                return None
            resp = qs.filter(user__isnull=True, device_id=device_id).first()
        return resp.answers if resp else None

    def get_response_count(self, obj):
        if obj.type != "survey" or not obj.questionnaire_id:
            return None
        return obj.questionnaire.responses.count()

    def get_schema_editable(self, obj):
        return can_edit_schema(obj)
