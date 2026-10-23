import io
import uuid
from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import F, OuterRef, Q, Subquery
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from common.policy import get_policy

from .authcode import generate_authcode_value, normalize_authcode
from .identity_review import approve_manual, disable_user, reject_manual
from .member_barcode import export_zip as export_barcode_zip
from .member_qr import export_zip
from .member_roster import (
    HEADERS,
    ParsedRow,
    RosterParseError,
    auto_match_identities,
    commit_import,
    parse_roster,
    plan_import,
)
from .models import (
    AuthCode,
    AuthCodeRedemption,
    IdentityImportBatch,
    IdentityProof,
    MemberIdentity,
    Profile,
    SecurityQuestion,
    StepUpEvent,
    Verification,
    can_manage_validity_for,
    is_verified,
)


# ---- 审核动作（#31 / ADR-0006）----
# 同时挂在 ProfileAdmin 与 IdentityProofAdmin：queryset 元素都有 .user，按 user 操作其
# manual 认证通道。仅持 accounts.can_review_identity 者可用（get_actions 收口 + 动作内二次校验）。
# 业务路径在 identity_review（与 /auth/identity-reviews/ API 共用）。


def approve_identity(modeladmin, request, queryset):
    """通过身份审核：manual 认证通道置 approved（+ verified_at / verified_by），并发邮件。"""
    if not get_policy().verification_enabled:
        modeladmin.message_user(
            request, "认证通道已关闭，无法通过身份审核。", level=messages.ERROR,
        )
        return
    count = 0
    for obj in queryset.select_related("user"):
        if not request.user.has_perm("accounts.can_review_identity"):
            continue  # 防御：get_actions 已收口，此处双保险
        approve_manual(obj.user, reviewer=request.user)
        count += 1
    modeladmin.message_user(request, f"已通过 {count} 个账号的身份审核。")


approve_identity.short_description = "通过身份审核"


def reject_identity(modeladmin, request, queryset):
    """驳回身份审核：manual 通道置 rejected，并发邮件提示可在面板重交（#38）。"""
    if not get_policy().verification_enabled:
        modeladmin.message_user(
            request, "认证通道已关闭，无法驳回身份审核。", level=messages.ERROR,
        )
        return
    count = 0
    for obj in queryset.select_related("user"):
        if not request.user.has_perm("accounts.can_review_identity"):
            continue
        reject_manual(obj.user, reviewer=request.user)
        count += 1
    modeladmin.message_user(request, f"已驳回 {count} 个账号的身份审核。")


reject_identity.short_description = "驳回身份审核"


def disable_account(modeladmin, request, queryset):
    """停用账号：置 is_active=False，并发邮件通知当事人联系信息组。"""
    count = 0
    for obj in queryset.select_related("user"):
        if not request.user.has_perm("accounts.can_review_identity"):
            continue
        disable_user(obj.user)
        count += 1
    modeladmin.message_user(request, f"已停用 {count} 个账号。")


disable_account.short_description = "停用账号"


_IDENTITY_ACTIONS = (approve_identity, reject_identity, disable_account)


class _IdentityReviewActionsMixin:
    """只把审核动作暴露给持 can_review_identity 者。"""

    def get_actions(self, request):
        actions = super().get_actions(request)  # type: ignore[misc]
        if not request.user.has_perm("accounts.can_review_identity"):
            for fn in _IDENTITY_ACTIONS:
                actions.pop(fn.__name__, None)
        return actions


class VerifiedFilter(admin.SimpleListFilter):
    """按账号「已认证」过滤（任一未过期 Verification 通道 approved 即已认证）。"""

    title = "认证状态"
    parameter_name = "verified"

    def lookups(self, request, model_admin):
        return [("yes", "已认证"), ("no", "未认证")]

    def queryset(self, request, qs):
        now = timezone.now()
        approved = Profile.objects.filter(
            user__pk__in=Verification.objects.filter(
                status=Verification.STATUS_APPROVED
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values_list("user_id", flat=True)
        )
        if self.value() == "yes":
            return qs.filter(pk__in=approved)
        if self.value() == "no":
            return qs.exclude(pk__in=approved)
        return qs


class ManualChannelStatusFilter(admin.SimpleListFilter):
    """按该用户人工通道 Verification 状态过滤身份证明行。"""

    title = "人工通道状态"
    parameter_name = "manual_status"

    def lookups(self, request, model_admin):
        return Verification.STATUSES

    def queryset(self, request, qs):
        value = self.value()
        if not value:
            return qs
        return qs.filter(
            user_id__in=Verification.objects.filter(
                channel=Verification.CHANNEL_MANUAL, status=value,
            ).values("user_id")
        )


class ProfileAdmin(_IdentityReviewActionsMixin, admin.ModelAdmin):
    list_display = ("user", "real_name", "identity", "verified", "deleted", "registration_deadline")
    list_filter = (VerifiedFilter, "identity", "deleted_at")
    search_fields = ("user__username", "user__email", "real_name")
    actions = list(_IDENTITY_ACTIONS)

    @admin.display(boolean=True, description="已认证")
    def verified(self, obj):
        return is_verified(obj.user)

    @admin.display(boolean=True, description="已注销")
    def deleted(self, obj):
        return obj.deleted_at is not None

    def get_readonly_fields(self, request, obj=None):
        # expiry_disabled_at / deleted_at / validity_notice_ack 系统维护；registration_deadline
        # 仅持 manage_validity 且改下位可改。
        ro = ["expiry_disabled_at", "deleted_at", "validity_notice_ack"]
        if obj is not None and not can_manage_validity_for(request.user, obj.user):
            ro.append("registration_deadline")
        return ro


class IdentityProofAdmin(_IdentityReviewActionsMixin, admin.ModelAdmin):
    """身份证明材料（审计留底）：只读浏览 + 审核动作；图经鉴权下载视图服务（不经公开 MEDIA_URL）。"""

    list_display = ("id", "user", "uploaded_at", "manual_channel_status", "proof_thumb")
    readonly_fields = ("user", "uploaded_at", "proof_image")
    search_fields = ("user__username", "user__email")
    list_filter = (ManualChannelStatusFilter, "uploaded_at")
    actions = list(_IDENTITY_ACTIONS)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        manual = Verification.objects.filter(
            user_id=OuterRef("user_id"),
            channel=Verification.CHANNEL_MANUAL,
        )
        return qs.annotate(manual_status=Subquery(manual.values("status")[:1]))

    # 永久留底：不允许增 / 改 / 删
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # 仅持 can_review_identity 者可见此审核台（含证明图）
    def has_module_permission(self, request):
        return request.user.has_perm("accounts.can_review_identity")

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("accounts.can_review_identity")

    @admin.display(description="人工通道状态", ordering="manual_status")
    def manual_channel_status(self, obj):
        status = getattr(obj, "manual_status", None)
        if not status:
            return "—"
        return dict(Verification.STATUSES).get(status, status)

    @admin.display(description="缩略图")
    def proof_thumb(self, obj):
        if not obj.pk:
            return "-"
        url = f"/auth/identity-proof/{obj.pk}/"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">'
            '<img src="{}" style="max-height:240px;border-radius:4px" />'
            "</a>",
            url,
            url,
        )

    @admin.display(description="证明材料")
    def proof_image(self, obj):
        if not obj.pk:
            return "-"
        proofs = IdentityProof.objects.filter(user_id=obj.user_id).order_by("-uploaded_at")
        return format_html_join(
            "",
            '<img src="/auth/identity-proof/{}/" alt="身份证明" '
            'style="max-width:100%;max-height:72vh;display:block;'
            'margin:0 auto 16px;border-radius:6px" />',
            ((p.pk,) for p in proofs),
        )


class ProfileInline(admin.StackedInline):
    model = Profile
    fk_name = "user"  # Profile 仅 user 一个 FK→User；显式绑定，防后续新增 FK 时歧义

    def get_readonly_fields(self, request, obj=None):
        # expiry_disabled_at / deleted_at / validity_notice_ack 系统维护；registration_deadline
        # 仅持 manage_validity 且改下位可改。
        ro = ["expiry_disabled_at", "deleted_at", "validity_notice_ack"]
        if not can_manage_validity_for(request.user, obj):
            ro.append("registration_deadline")
        return ro


class VerificationInline(admin.TabularInline):
    """用户详情页内嵌认证通道（ADR-0041）：expires_at 可改 = 修改有效期。

    通道由系统 / 流程创建，不手建、不删除；「有效期至」仅在当前操作者持
    accounts.manage_validity 且目标是下位权限用户时可编辑（平级 / 上位拒绝）。
    """

    model = Verification
    fk_name = "user"  # Verification 有 user 与 verified_by 两个 User FK，显式绑定
    extra = 0
    can_delete = False
    fields = ("channel", "status", "identifier", "verified_at", "expires_at")
    readonly_fields = ("channel", "status", "identifier", "verified_at")

    def has_add_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if not can_manage_validity_for(request.user, obj):
            ro.append("expires_at")
        return ro


class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active", "deleted")
    list_filter = ("is_staff", "is_active", "profile__deleted_at")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)
    inlines = [ProfileInline, VerificationInline]
    actions = ["ban_users", "mute_users"]

    def get_queryset(self, request):
        # 已注销列读 profile.deleted_at：一次性 select_related，避免列表 N+1。
        return super().get_queryset(request).select_related("profile")

    @admin.display(boolean=True, description="已注销")
    def deleted(self, obj):
        profile = getattr(obj, "profile", None)
        return bool(profile and profile.deleted_at)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("reviews.mute_user"):
            actions.pop("mute_users", None)
        return actions

    @admin.action(description="封禁")
    def ban_users(self, request, queryset):
        """批量封禁：停用账号、吊销会话、发邮件。不可封禁自己或超级管理员。"""
        ok = skip = 0
        for user in queryset:
            if user.pk == request.user.pk or user.is_superuser or not user.is_active:
                skip += 1
                continue
            disable_user(user)
            ok += 1
        self.message_user(request, f"已封禁 {ok} 个账号。跳过 {skip} 个。")

    @admin.action(description="全站禁言")
    def mute_users(self, request, queryset):
        """批量全站禁言（永久）。需 reviews.mute_user；已禁言 / 自己跳过。"""
        from messaging.services import MessagingError
        from reviews.discipline import mute_user

        if not request.user.has_perm("reviews.mute_user"):
            self.message_user(request, "没有全站禁言权限。", level=messages.ERROR)
            return
        ok = skip = 0
        for user in queryset:
            try:
                mute_user(request.user, user, reason="后台批量禁言")
                ok += 1
            except MessagingError:
                skip += 1
        self.message_user(request, f"已禁言 {ok} 个账号。跳过 {skip} 个。")


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(Profile, ProfileAdmin)
admin.site.register(IdentityProof, IdentityProofAdmin)


# ---- 认证码（ADR-0020，生成侧）----
# 生成 / 吊销全在 Django 后台（不建前端管理页）；权限 = 标准 CRUD
# （accounts.add_authcode / view / change / delete，由 0012 授权迁移授给 社长 / 信息组；
# 后台操作需 is_staff）。生成 / 吊销不受站点「认证通道」开关约束（可先备码）；
# 兑换侧受约束（见 views.verification_authcode_redeem_view）。


class AuthCodeStatusFilter(admin.SimpleListFilter):
    """按派生状态过滤：有效 / 已过期 / 已用尽 / 已吊销（优先级：吊销 > 过期 > 用尽）。"""

    title = "状态"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [
            ("valid", "有效"),
            ("expired", "已过期"),
            ("exhausted", "已用尽"),
            ("revoked", "已吊销"),
        ]

    def queryset(self, request, qs):
        value = self.value()
        if not value:
            return qs
        now = timezone.now()
        if value == "revoked":
            return qs.filter(revoked_at__isnull=False)
        qs = qs.filter(revoked_at__isnull=True)
        if value == "expired":
            return qs.filter(expires_at__lte=now)
        qs = qs.filter(expires_at__gt=now)
        if value == "exhausted":
            return qs.filter(used_count__gte=F("max_uses"))
        if value == "valid":
            return qs.filter(used_count__lt=F("max_uses"))
        return qs


class AuthCodeAdminForm(forms.ModelForm):
    """后台表单：码值归一化（去空格 / 连字符、转大写）后做唯一校验。"""

    class Meta:
        model = AuthCode
        fields = "__all__"

    def clean_code(self):
        value = normalize_authcode(self.cleaned_data.get("code", ""))
        if not value:
            raise forms.ValidationError("请输入有效的认证码。")
        return value


@admin.action(description="吊销认证码（不回溯已通过者）")
def revoke_authcodes(modeladmin, request, queryset):
    """软吊销：只停后续兑换，不改已通过用户的认证状态。"""
    if not request.user.has_perm("accounts.change_authcode"):
        modeladmin.message_user(request, "没有吊销认证码的权限。", level=messages.ERROR)
        return
    now = timezone.now()
    count = 0
    for obj in queryset:
        if obj.revoked_at is not None:
            continue
        obj.revoked_at = now
        obj.save(update_fields=["revoked_at"])
        count += 1
    modeladmin.message_user(request, f"已吊销 {count} 个认证码（已吊销的跳过）。")


class AuthCodeRedemptionInline(admin.TabularInline):
    """码详情页内嵌兑换记录（只读）。"""

    model = AuthCodeRedemption
    extra = 0
    can_delete = False
    readonly_fields = ("user", "redeemed_at")

    def has_add_permission(self, request, obj=None):
        return False


class AuthCodeAdmin(admin.ModelAdmin):
    """认证码：后台直接创造（新增预生成 12 位码、可手改）+ 软吊销 + 删除规则。"""

    form = AuthCodeAdminForm
    fields = ("code", "note", "expires_at", "max_uses", "used_count", "created_by", "created_at", "revoked_at")
    list_display = ("code", "status_display", "uses_display", "expires_at", "created_by", "note", "created_at")
    list_filter = (AuthCodeStatusFilter, "created_by", "created_at")
    search_fields = ("code", "note", "created_by__username")
    inlines = [AuthCodeRedemptionInline]
    actions = [revoke_authcodes]
    ordering = ("-created_at",)

    def get_readonly_fields(self, request, obj=None):
        # 生成后：码 / 可用次数 / 生成人不可改；备注与有效期可改（「延期」场景）。
        if obj is None:
            return ("created_by", "created_at", "used_count", "revoked_at")
        return ("code", "max_uses", "created_by", "created_at", "used_count", "revoked_at")

    def get_changeform_initial_data(self, request):
        # 新增表单自动预生成 12 位码（可手改 = 自定义码）；有效期初始「当前 +30 天」。
        return {
            "code": generate_authcode_value(),
            "expires_at": timezone.now() + timedelta(days=30),
            "max_uses": 1,
        }

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user  # 生成人自动 = 当前操作者
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        # 仅从未使用且未吊销的码可删（纠错清理）；其余留审计。
        if obj is not None and (obj.used_count > 0 or obj.revoked_at is not None):
            return False
        return super().has_delete_permission(request, obj)

    @admin.display(description="状态")
    def status_display(self, obj):
        return {
            "valid": "有效",
            "expired": "已过期",
            "exhausted": "已用尽",
            "revoked": "已吊销",
        }.get(obj.status, obj.status)

    @admin.display(description="已用次数")
    def uses_display(self, obj):
        return f"{obj.used_count}/{obj.max_uses}"


class AuthCodeRedemptionAdmin(admin.ModelAdmin):
    """兑换记录（审计）：全局只读追溯，按用户 / 码搜索；随认证码查看权限可见。"""

    list_display = ("user", "authcode", "redeemed_at")
    search_fields = ("user__username", "user__email", "authcode__code")
    list_filter = ("redeemed_at",)

    def has_module_permission(self, request):
        return request.user.has_perm("accounts.view_authcode")

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("accounts.view_authcode")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(AuthCode, AuthCodeAdmin)
admin.site.register(AuthCodeRedemption, AuthCodeRedemptionAdmin)


# ---- 社员身份编号（ADR-0025）----
# 名册模块整体由命名工作流权限 accounts.manage_member_roster 收口：
# 列表 / 编辑 / 导入 / 导出二维码 / 自动重匹配 / 解绑，全部走同一枚权限。

_ROSTER_PERM = "accounts.manage_member_roster"


def _rows_to_payload(rows):
    """ParsedRow → 可缓存的纯数据（预检与确认之间暂存）。"""
    return [
        {
            "row_no": r.row_no,
            "values": r.values,
            "errors": list(r.errors),
            "warnings": list(r.warnings),
        }
        for r in rows
    ]


def _rows_from_payload(payload):
    return [
        ParsedRow(
            row_no=item["row_no"],
            values=item["values"],
            errors=list(item.get("errors", [])),
            warnings=list(item.get("warnings", [])),
        )
        for item in payload
    ]


class MemberIdentityBoundFilter(admin.SimpleListFilter):
    title = "绑定状态"
    parameter_name = "bound"

    def lookups(self, request, model_admin):
        return [("yes", "已绑定"), ("no", "未绑定")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(user__isnull=False)
        if self.value() == "no":
            return queryset.filter(user__isnull=True)
        return queryset


@admin.action(description="导出二维码（ZIP / PNG）")
def export_member_qr(modeladmin, request, queryset):
    """批量导出所选社员身份的二维码（文件名：识别码_姓名.png，512px 上下）。"""
    rows = list(queryset.order_by("code"))
    if not rows:
        modeladmin.message_user(request, "没有可导出的行。", level=messages.WARNING)
        return
    payload = export_zip(rows)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = HttpResponse(payload, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="member-qr-{stamp}.zip"'
    return response


@admin.action(description="导出条形码（扫码枪读取识别码 · ZIP / PNG）")
def export_member_barcode(modeladmin, request, queryset):
    """批量导出所选社员身份的 Code128 条形码（文件名：识别码_姓名.png；内容 = 裸识别码）。

    定位：仅供扫码枪 / 手工输入到后台检索。微信等手机扫码软件扫一维条码只会显示数字、
    不会打开链接（2026-10-19 实测）——「扫码打开校验页」请用二维码导出（带签名 URL）。
    """
    rows = list(queryset.order_by("code"))
    if not rows:
        modeladmin.message_user(request, "没有可导出的行。", level=messages.WARNING)
        return
    payload = export_barcode_zip(rows)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = HttpResponse(payload, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="member-barcode-{stamp}.zip"'
    return response


@admin.action(description="重新运行自动匹配（所选未绑定行）")
def rerun_member_match(modeladmin, request, queryset):
    matched = auto_match_identities(rows=list(queryset))
    modeladmin.message_user(request, f"自动匹配完成：新绑定 {matched} 条。")


@admin.action(description="解绑账号（保留名册行）")
def unbind_member_identity(modeladmin, request, queryset):
    count = 0
    for row in queryset.filter(user__isnull=False):
        row.user = None
        row.bound_at = None
        row.bound_by = None
        row.bind_method = ""
        row.save(update_fields=["user", "bound_at", "bound_by", "bind_method", "updated_at"])
        count += 1
    modeladmin.message_user(request, f"已解绑 {count} 条。")


class MemberIdentityAdmin(admin.ModelAdmin):
    """社员身份：名册行管理 + 导入子页面（两步式）+ 二维码导出。"""

    change_list_template = "admin/accounts/memberidentity/change_list.html"

    list_display = (
        "name", "cohort", "group", "code", "user_display",
        "bind_method_display", "status", "phone",
    )
    list_filter = (MemberIdentityBoundFilter, "cohort", "group", "status")
    search_fields = ("name", "code", "phone", "user__username")
    actions = (export_member_qr, export_member_barcode, rerun_member_match, unbind_member_identity)
    readonly_fields = ("bound_at", "bound_by", "bind_method", "created_at", "updated_at")
    fieldsets = (
        (
            "名册信息",
            {"fields": ("name", "grade", "class_no", "student_no", "admit_year",
                        "joined_on_raw", "cohort", "group", "gender", "age", "phone")},
        ),
        ("编号", {"fields": ("code", "status")}),
        ("绑定", {"fields": ("user", "bind_method", "bound_at", "bound_by", "import_batch")}),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "user" in form.base_fields:
            form.base_fields["user"].required = False  # 允许置空 = 解绑
        return form

    def save_model(self, request, obj, form, change):
        # 后台手动绑定 / 解绑时补记绑定元数据（只在 user 变化时动）。
        if change:
            previous = (
                MemberIdentity.objects.filter(pk=obj.pk)
                .values_list("user_id", flat=True)
                .first()
            )
            if previous != obj.user_id:
                if obj.user_id:
                    obj.bound_at = timezone.now()
                    obj.bound_by = request.user
                    obj.bind_method = MemberIdentity.BIND_ADMIN
                else:
                    obj.bound_at = None
                    obj.bound_by = None
                    obj.bind_method = ""
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm(_ROSTER_PERM):
            for name in ("export_member_qr", "export_member_barcode", "rerun_member_match", "unbind_member_identity"):
                actions.pop(name, None)
        return actions

    # ---- 模块权限收口（全部走 manage_member_roster；超管天然放行）----
    def has_module_permission(self, request):
        return request.user.has_perm(_ROSTER_PERM)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(_ROSTER_PERM)

    def has_add_permission(self, request):
        return request.user.has_perm(_ROSTER_PERM)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(_ROSTER_PERM)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="绑定账号")
    def user_display(self, obj):
        return obj.user.username if obj.user_id else "—"

    @admin.display(description="绑定方式")
    def bind_method_display(self, obj):
        return obj.get_bind_method_display() if obj.bind_method else "—"

    # ---- 导入子页面（上传 → 预检 → 确认）+ 模板下载 ----
    def get_urls(self):
        custom = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_view),
                name="accounts_memberidentity_import",
            ),
            path(
                "import/template/",
                self.admin_site.admin_view(self.template_view),
                name="accounts_memberidentity_import_template",
            ),
        ]
        return custom + super().get_urls()

    def _require_roster_perm(self, request):
        if not request.user.has_perm(_ROSTER_PERM):
            raise PermissionDenied

    def import_view(self, request):
        self._require_roster_perm(request)
        context = {
            **self.admin_site.each_context(request),
            "title": "导入名册",
            "opts": self.model._meta,
            "headers": HEADERS,
            "preview": None,
            "report": None,
        }

        if request.method == "POST" and request.POST.get("cancel"):
            pass  # 取消：留在上传态

        elif request.method == "POST" and request.POST.get("stash"):
            stash_key = f"member-roster-import:{request.POST.get('stash')}"
            stash = cache.get(stash_key)
            if stash is None:
                messages.error(request, "预检数据已过期，请重新上传。")
            else:
                batch = commit_import(
                    _rows_from_payload(stash["rows"]),
                    file_name=stash["file_name"],
                    operator=request.user,
                )
                cache.delete(stash_key)
                report = dict(batch.summary or {})
                report["file_name"] = batch.file_name
                context["report"] = report

        elif request.method == "POST" and request.FILES.get("file"):
            upload = request.FILES["file"]
            try:
                rows = parse_roster(upload.name, upload.read())
            except RosterParseError as exc:
                messages.error(request, str(exc))
            else:
                plan = plan_import(rows)
                stash_id = uuid.uuid4().hex
                cache.set(
                    f"member-roster-import:{stash_id}",
                    {"file_name": upload.name, "rows": _rows_to_payload(rows)},
                    timeout=900,
                )
                context["preview"] = {
                    "stash_id": stash_id,
                    "file_name": upload.name,
                    "counts": plan["counts"],
                    "items": [
                        {
                            "row_no": item["row"].row_no,
                            "name": item["row"].values.get("姓名", ""),
                            "cohort": item["row"].values.get("届数", ""),
                            "group": item["row"].values.get("组别", ""),
                            "action": item["action"],
                            "code": item["code"] or "",
                            "note": item["note"],
                        }
                        for item in plan["items"]
                    ],
                }

        return render(request, "admin/accounts/memberidentity/import.html", context)

    def template_view(self, request):
        self._require_roster_perm(request)
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "名册"
        sheet.append(HEADERS)
        sheet.append(["张三", "高一", "1", "1", 2026, "20260303", 2, "摄影", "男", 16, "13800000000", ""])
        buffer = io.BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="member-roster-template.xlsx"'
        return response


class IdentityImportBatchAdmin(admin.ModelAdmin):
    """导入批次（审计）：只读列表，随名册管理权限可见。"""

    list_display = ("file_name", "uploaded_by", "uploaded_at", "summary_display")
    list_filter = ("uploaded_at",)
    search_fields = ("file_name", "uploaded_by__username")

    def has_module_permission(self, request):
        return request.user.has_perm(_ROSTER_PERM)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(_ROSTER_PERM)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="统计")
    def summary_display(self, obj):
        s = obj.summary or {}
        if not s:
            return "—"
        return (
            f"新增 {s.get('created', 0)} · 更新 {s.get('updated', 0)} · "
            f"冲突 {s.get('conflicts', 0)} · 错误 {s.get('errors', 0)} · "
            f"自动绑定 {s.get('auto_matched', 0)}"
        )


admin.site.register(MemberIdentity, MemberIdentityAdmin)
admin.site.register(IdentityImportBatch, IdentityImportBatchAdmin)


# ---- 安全验证（Step-up，ADR-0026）----


@admin.register(SecurityQuestion)
class SecurityQuestionAdmin(admin.ModelAdmin):
    """安全问题（安全验证）：供信息组排查 / 重置；答案只存哈希（后台不可见明文）。"""

    list_display = ("user", "question_text", "created_at", "updated_at")
    search_fields = ("user__username", "user__email", "question_text")
    ordering = ("-created_at",)


@admin.register(StepUpEvent)
class StepUpEventAdmin(admin.ModelAdmin):
    """安全验证记录（审计，只读）：谁 / 何时 / 哪方式 / 成败 / IP。"""

    list_display = ("user", "scope", "method", "result", "ip", "created_at")
    list_filter = ("scope", "method", "result")
    search_fields = ("user__username",)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
