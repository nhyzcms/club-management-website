"""明信片互寄序列化与输入校验。

公开输入（登记 / 建议）是访客可控数据，校验从严：长度、枚举、格式全部
在序列化层收口，视图层只做业务判定（phase / 条码占用 / 学校清单）。
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from rest_framework import serializers
from rest_framework.utils import html as drf_html

from .models import PostcardConfig, PostcardPhoto, PostcardRegistration

_BARCODE_RE = re.compile(r"^\d{7}$")
_REGCODE_RE = re.compile(r"^\d{6}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{8,128}$")


class JSONListField(serializers.ListField):
    """multipart 下的列表字段。

    HTML 表单只能提交字符串：前端 FormData 无法直接携带 ``[{...}]``，只能在
    ``destination_schools`` 里塞一段 JSON 串。DRF 默认会把它当 ``["{...}"]``
    交给子字段，DictField 立刻报错。这里只在「请求是 html 输入且值是 JSON 数组」
    时先解码，JSON 请求（list 原样）走父类行为，两种 content-type 结果一致。
    """

    def get_value(self, dictionary):
        if drf_html.is_html_input(dictionary):
            raw = dictionary.get(self.field_name, serializers.empty)
            if isinstance(raw, str) and raw.strip().startswith("["):
                try:
                    return json.loads(raw)
                except ValueError:
                    pass
        return super().get_value(dictionary)

#: 单次登记最多明信片张数（照片 = 张数 × 2，防 multipart 炸内存）。
MAX_ITEMS_PER_REGISTRATION = 5


class RegisterItemInput(serializers.Serializer):
    barcode = serializers.CharField(max_length=7)

    def validate_barcode(self, value):
        value = (value or "").strip()
        if not _BARCODE_RE.fullmatch(value):
            raise serializers.ValidationError("条码号须为 7 位数字")
        return value


class RegisterInput(serializers.Serializer):
    """登记提交（multipart：JSON 字段 + photo_<i>_front/back 文件由视图另取）。"""

    sender_name = serializers.CharField(max_length=64, trim_whitespace=True)
    grade = serializers.ChoiceField(choices=PostcardConfig.GRADE_CHOICES)
    class_no = serializers.IntegerField(min_value=1, max_value=8)
    dest_region = serializers.CharField(max_length=64, trim_whitespace=True)
    dest_school = serializers.CharField(max_length=128, trim_whitespace=True)
    items = RegisterItemInput(many=True, allow_empty=False)
    fingerprint = serializers.CharField(required=False, allow_blank=True, max_length=128)

    def validate_sender_name(self, value):
        if not value:
            raise serializers.ValidationError("姓名不能为空")
        return value

    def validate_items(self, value):
        if len(value) > MAX_ITEMS_PER_REGISTRATION:
            raise serializers.ValidationError(
                f"单次最多登记 {MAX_ITEMS_PER_REGISTRATION} 张明信片"
            )
        barcodes = [it["barcode"] for it in value]
        if len(set(barcodes)) != len(barcodes):
            raise serializers.ValidationError("登记的条码号不能重复")
        return value

    def validate_fingerprint(self, value):
        if value and not _FINGERPRINT_RE.fullmatch(value):
            return ""  # 指纹格式不对不致命：静默降级为仅 Cookie 识别
        return value


class SuggestionInput(serializers.Serializer):
    content = serializers.CharField(max_length=1000, trim_whitespace=True)
    contact = serializers.CharField(required=False, allow_blank=True, max_length=128)


class MyRecordEditInput(serializers.Serializer):
    """用户改自己的登记（仅寄出人信息；条码与照片不可改——实物已印好）。"""

    sender_name = serializers.CharField(required=False, max_length=64, trim_whitespace=True)
    grade = serializers.ChoiceField(choices=PostcardConfig.GRADE_CHOICES, required=False)
    class_no = serializers.IntegerField(required=False, min_value=1, max_value=8)
    dest_region = serializers.CharField(required=False, max_length=64, trim_whitespace=True)
    dest_school = serializers.CharField(required=False, max_length=128, trim_whitespace=True)


class AdminConfigInput(serializers.Serializer):
    """管理端配置写入：Event 壳字段 + 模块节点/清单字段。"""

    title = serializers.CharField(max_length=200)
    summary = serializers.CharField(required=False, allow_blank=True, max_length=300)
    body = serializers.CharField(required=False, allow_blank=True)
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()
    ship_at = serializers.DateTimeField(required=False, allow_null=True)
    distribute_at = serializers.DateTimeField(required=False, allow_null=True)
    allowed_grades = serializers.ListField(
        child=serializers.ChoiceField(choices=PostcardConfig.GRADE_CHOICES),
        required=False, allow_empty=True,
    )
    destination_schools = JSONListField(
        child=serializers.DictField(), required=False, allow_empty=True,
    )

    def validate(self, attrs):
        start, end = attrs.get("start_at"), attrs.get("end_at")
        if start and end and end <= start:
            raise serializers.ValidationError({"end_at": "结束时间必须晚于开始时间"})
        ship, dist = attrs.get("ship_at"), attrs.get("distribute_at")
        if ship and start and ship < start:
            raise serializers.ValidationError({"ship_at": "寄出节点不能早于登记开始"})
        if dist and ship and dist < ship:
            raise serializers.ValidationError({"distribute_at": "下发节点不能早于寄出节点"})
        if dist and start and dist < start:
            raise serializers.ValidationError({"distribute_at": "下发节点不能早于登记开始"})
        if end and ship and ship > end:
            raise serializers.ValidationError({"ship_at": "寄出节点不能晚于活动结束"})
        if end and dist and dist > end:
            raise serializers.ValidationError({"distribute_at": "下发节点不能晚于活动结束"})
        schools = attrs.get("destination_schools") or []
        for s in schools:
            if not isinstance(s, dict) or not s.get("name"):
                raise serializers.ValidationError({"destination_schools": "每个寄达校须含 name"})
            region = (s.get("region") or "").strip()
            if not region:
                raise serializers.ValidationError({"destination_schools": "每个寄达校须含 region"})
            if region not in PostcardConfig.REGION_CHOICES:
                raise serializers.ValidationError(
                    {"destination_schools": f"寄达区「{region}」不在固定 16 区清单内"}
                )
            # 区内编号（「浦东新区1」→ no=1）：缺省保留兼容旧清单；给了就必须是
            # 1~9999 的整数，否则前端排序会得到不可预期的顺序。
            no = s.get("no")
            if no not in (None, ""):
                try:
                    no_int = int(no)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        {"destination_schools": f"学校「{s.get('name')}」的编号须为数字"}
                    )
                if not 0 < no_int <= 9999:
                    raise serializers.ValidationError(
                        {"destination_schools": f"学校「{s.get('name')}」的编号须在 1~9999 之间"}
                    )
                s["no"] = no_int
        return attrs


class AdminRegistrationEditInput(serializers.Serializer):
    """管理端改登记单：寄出人信息 + 状态（cancelled 联动全部条目）。"""

    sender_name = serializers.CharField(required=False, max_length=64)
    grade = serializers.ChoiceField(choices=PostcardConfig.GRADE_CHOICES, required=False)
    class_no = serializers.IntegerField(required=False, min_value=1, max_value=8)
    dest_region = serializers.CharField(required=False, max_length=64)
    dest_school = serializers.CharField(required=False, max_length=128)
    status = serializers.ChoiceField(choices=PostcardRegistration.STATUS_CHOICES, required=False)


class AIConfigInput(serializers.Serializer):
    """AI 审核配置写入（全局单例）。``api_key`` 留空 = 保持原值（写后不可读，
    前端拿不到明文，只能整体换新）。"""

    base_url = serializers.CharField(required=False, allow_blank=True, max_length=256, trim_whitespace=True)
    api_key = serializers.CharField(required=False, allow_blank=True, max_length=512, trim_whitespace=True)
    model = serializers.CharField(required=False, allow_blank=True, max_length=128, trim_whitespace=True)
    extra_headers = serializers.DictField(required=False, allow_empty=True)
    timeout_seconds = serializers.IntegerField(required=False, min_value=5, max_value=120)
    # 采样温度：0–2，步进 0.1（越低越确定，越高越发散）。
    temperature = serializers.DecimalField(
        required=False, max_digits=3, decimal_places=1,
        min_value=Decimal("0"), max_value=Decimal("2"),
    )
    ip_blacklist = serializers.ListField(
        child=serializers.CharField(max_length=128, trim_whitespace=True),
        required=False, allow_empty=True,
    )
    # 前置提示词：多行文本，保留换行与缩进（不 trim），上限防超大 prompt 打爆 token。
    prompt_prefix = serializers.CharField(
        required=False, allow_blank=True, max_length=4000, trim_whitespace=False,
    )
    enabled = serializers.BooleanField(required=False)

    def validate_base_url(self, value):
        if value and not value.startswith(("http://", "https://")):
            raise serializers.ValidationError("Base URL 必须以 http(s):// 开头")
        return value.rstrip("/")

    def validate_extra_headers(self, value):
        for key, val in (value or {}).items():
            if not isinstance(key, str) or not isinstance(val, str):
                raise serializers.ValidationError("自定义请求头的键值都必须是字符串")
            if not key.strip():
                raise serializers.ValidationError("请求头键不能为空")
        return value

    def validate_ip_blacklist(self, value):
        return [v for v in (value or []) if v.strip()]


class ReviewDecisionInput(serializers.Serializer):
    """人工复核判定：pass = 通过（照片即删），fail = 不通过。"""

    DECISIONS = ["pass", "fail"]

    decision = serializers.ChoiceField(choices=DECISIONS)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, trim_whitespace=True)


def item_review_info(item) -> dict:
    """条目 → 审核状态摘要（两面照片状态由 ai 层保证同进同出，取首张即可）。

    ``mismatched`` 即「告知用户哪里填错」的数据源（ai_verdict.mismatched_items）。
    ``photos`` 供用户侧历史记录构造鉴权照片 URL（PhotoView：登记码 + 三轨归属）。
    """
    photos = list(item.photos.all())
    if not photos:
        return {
            "review_state": None, "review_label": None, "mismatched": [], "comment": "",
            "photos": [],
        }
    verdict = next((p.ai_verdict for p in photos if p.ai_verdict), None) or {}
    return {
        "review_state": photos[0].review_state,
        "review_label": photos[0].get_review_state_display(),
        "mismatched": verdict.get("mismatched_items") or [],
        "comment": verdict.get("comment") or "",
        "photos": [{"id": p.pk, "side": p.side} for p in photos],
    }


#: 登记码发放规则（2026-11-08 用户指定，**服务端权威**，不再只靠前端弹窗）：
#: - 存在失败条目（AI 判不匹配 / 人工不通过）→ 不发码；
#: - 已转人工复核 → 立即发码（不等人工结果）；
#: - 全部通过（AI / 人工）→ 发码；
#: - 仍在 AI 审核（pending）→ 不发码。
_CODE_FAILED = {PostcardPhoto.REVIEW_AI_FAILED, PostcardPhoto.REVIEW_MANUAL_FAILED}
_CODE_PASSED = {PostcardPhoto.REVIEW_AI_PASSED, PostcardPhoto.REVIEW_MANUAL_PASSED}


def code_granted(reg: PostcardRegistration) -> bool:
    """这条提交现在是否该把 6 位登记码发给用户。"""
    states: set[str] = set()
    for item in reg.items.all():
        for photo in item.photos.all():
            states.add(photo.review_state)
    if states & _CODE_FAILED:
        return False
    if PostcardPhoto.REVIEW_MANUAL_PENDING in states:
        return True
    if states and states <= _CODE_PASSED:
        return True
    return False


def mask_code(reg_code: str) -> str:
    """未发放时的掩码（与姓名查询同形：前 2 位 + ****）。"""
    return f"{reg_code[:2]}****"


def registration_summary(
    reg: PostcardRegistration, *, include_items: bool = True, force_code: bool = False,
) -> dict:

    """登记单 → 前端展示 dict（公开侧与管理端共用）。

    ``force_code=True``：调用方已出示完整登记码（详情 / 管理端），照原样返回；
    否则按发放规则掩码，避免「审核未过也拿到能力凭证」。
    """
    granted = force_code or code_granted(reg)
    data = {
        "reg_code": reg.reg_code if granted else mask_code(reg.reg_code),
        "code_granted": granted,
        "sender_name": reg.sender_name,
        "grade": reg.grade,
        "grade_label": reg.grade_label,
        "class_no": reg.class_no,
        "dest_region": reg.dest_region,
        "dest_school": reg.dest_school,
        "status": reg.status,
        "status_label": reg.get_status_display(),
        "created_at": reg.created_at.isoformat(),
        "updated_at": reg.updated_at.isoformat(),
    }
    if include_items:
        data["items"] = [
            {
                "id": item.pk,
                "barcode": item.barcode.code,
                "status": item.status,
                "status_label": item.get_status_display(),
                **item_review_info(item),
            }
            for item in reg.items.select_related("barcode").prefetch_related("photos").order_by("barcode__code")
        ]
    return data
