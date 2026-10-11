import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone


def avatar_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1]
    return f"avatars/user_{instance.user_id}{ext}"


# 私有文件存储：身份证明落 PRIVATE_MEDIA_ROOT（与公开 MEDIA_ROOT 隔离），
# 绝不经 config/urls.py 的 static(MEDIA_URL) 公开服务；由带鉴权的下载视图提供（#31）。
# 用 callable 而非实例：migration 序列化函数引用、运行期按 settings 解析路径，避免绝对路径入库。
def private_media_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def identity_proof_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"identity_proofs/user_{instance.user_id}_{uuid.uuid4().hex}{ext}"


class Profile(models.Model):
    GENDER_CHOICES = [
        ("M", "男"),
        ("F", "女"),
        ("O", "其他"),
    ]
    IDENTITY_CHOICES = [
        ("student", "在校生"),
        ("external", "外校生"),
        ("graduate", "毕业生"),
        ("parent", "家长"),
        ("teacher", "教师"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True)
    nickname = models.CharField(max_length=50, blank=True)
    birthday = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    bio = models.TextField(blank=True)

    # 可选资料（ADR-0006 决策 3）：real_name 不公开（仅本人 / 审核员可见），在提交身份证明
    # 时收集；identity 是纯元数据，不影响权限。验证态不在 Profile 上——见 Verification。
    real_name = models.CharField("真实姓名", max_length=100, blank=True)
    identity = models.CharField("身份", max_length=10, choices=IDENTITY_CHOICES, blank=True)

    # 身份有效期（ADR-0041）：注册验证宽限覆盖 + 因超期停用标记。
    # registration_deadline 为 null = 按 date_joined + 站点「注册后验证宽限」起算；
    # 持 manage_validity 者可对下位用户显式延/缩。
    registration_deadline = models.DateTimeField("注册验证截止", null=True, blank=True)
    # expiry_disabled_at 标记「因注册超期未认证被系统停用」，用于登录时给专属提示；
    # 系统维护，不可手改。
    expiry_disabled_at = models.DateTimeField("因超期停用时间", null=True, blank=True)

    def __str__(self):
        return f"{self.user.username}'s profile"


class Verification(models.Model):
    """验证通道当前状态（ADR-0006）：每 (user, channel) 一行，in-place 更新。

    账号「已验证」⇔ 任一通道 ``status=approved`` 且未过期（见 :func:`is_verified`）。
    通道是一等公民：邮箱、人工审批、后台委任、认证码是通道；加通道 = 加 choices + 实现
    该通道流程，核心判定（任一 approved）不动。

    - ``identifier`` 是通道主体：邮箱=待验地址（验证前住此、不进 ``User.email``）；人工=空；
      后台委任=``staff`` / ``superuser``。
    - ``expires_at``（ADR-0041）是该通道的认证有效期：认证通道 = 通过日 + 认证有效期；
      委任通道 = 委任日 + 管理员有效期（超管 null=永久）。null=永久不过期。
    - 审计走 ``IdentityProof``（人工通道证据，永久留底）；本表不留尝试历史。
    """

    CHANNEL_APPOINTMENT = "appointment"
    CHANNEL_EMAIL = "email"
    CHANNEL_MANUAL = "manual"
    CHANNEL_AUTHCODE = "authcode"
    CHANNELS = [
        (CHANNEL_APPOINTMENT, "后台委任"),
        (CHANNEL_EMAIL, "邮箱"),
        (CHANNEL_MANUAL, "人工审批"),
        (CHANNEL_AUTHCODE, "认证码"),
    ]

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUSES = [
        (STATUS_PENDING, "待验证"),
        (STATUS_APPROVED, "已通过"),
        (STATUS_REJECTED, "已驳回"),
    ]

    user = models.ForeignKey(
        User, verbose_name="用户", on_delete=models.CASCADE, related_name="verifications"
    )
    channel = models.CharField("通道", max_length=20, choices=CHANNELS)
    status = models.CharField("状态", max_length=10, choices=STATUSES, default=STATUS_PENDING)
    identifier = models.CharField("通道标识", max_length=254, blank=True, default="")
    verified_at = models.DateTimeField("通过时间", null=True, blank=True)
    verified_by = models.ForeignKey(
        User, verbose_name="审核人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="verifications_reviewed",
    )
    expires_at = models.DateTimeField("有效期至", null=True, blank=True)

    class Meta:
        verbose_name = "验证通道"
        verbose_name_plural = "验证通道"
        constraints = [
            models.UniqueConstraint(fields=["user", "channel"], name="unique_user_channel"),
        ]
        indexes = [models.Index(fields=["user", "status"])]
        ordering = ["user", "channel"]
        permissions = [
            ("manage_validity", "可以管理账号 / 认证有效期"),
        ]

    def __str__(self):
        return f"{self.user.username} · {self.get_channel_display()} · {self.get_status_display()}"


def profile_of(user):
    """取 ``user.profile``，无则 None（防御：老数据 / 未建 Profile）。"""
    if user is None or not getattr(user, "pk", None):
        return None
    try:
        return user.profile
    except Profile.DoesNotExist:
        return None


def _policy_attr(attr):
    from common.policy import get_policy

    return getattr(get_policy(), attr)


def verification_valid_days():
    return _policy_attr("verification_valid_days")


def admin_valid_days():
    return _policy_attr("admin_valid_days")


def registration_verify_days():
    return _policy_attr("registration_verify_days")


def _unexpired_filter():
    """``(expires_at 为空 或 晚于现在)``——未过期通道的公共过滤条件。"""
    now = timezone.now()
    return models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)


def has_ever_verified(user):
    """是否曾完成过任一验证（``verified_at`` 非空）。

    用于区分「从未验证」（适用注册 60 天宽限停用）与「验证后过期」（不适用该停用，
    只回落为访客、需重新认证）。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return user.verifications.filter(verified_at__isnull=False).exists()


def is_verified(user):
    """账号「已验证」单一计算源（ADR-0006 + ADR-0041）。

    任一验证通道 ``approved`` 且未过期即真。``expires_at=null`` 视为永久（超管委任 /
    后台显式延长）。过期通道不再算已验证，账号回落为访客、需重新认证。

    纯计算：不读 ``is_staff`` / ``is_superuser``（ADR-0013）。超管 / 管理员经后台委任通道
    计入（超管委任 expires_at=null 永久），不在本函数内特判标志位。权限轴逃生舱仍是
    ``has_perm`` 对超管恒真（ADR-0005 决策 9），不在本函数。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return user.verifications.filter(status=Verification.STATUS_APPROVED).filter(
        _unexpired_filter()
    ).exists()


def admin_identity_valid(user):
    """管理员身份是否有效（ADR-0041）：看委任通道是否未过期。

    纯计算：不读 ``is_superuser``。超管委任通道 expires_at=null 永久，故恒有效；
    staff 委任通道 = 委任日 + 管理员有效期，过期即无效（需重新授予）。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not user.is_staff:
        return False
    return user.verifications.filter(
        channel=Verification.CHANNEL_APPOINTMENT,
        status=Verification.STATUS_APPROVED,
    ).filter(_unexpired_filter()).exists()


def rank_of(user):
    """权限层级：超级管理员(3) > 管理员(2) > 已验证用户(1) > 未验证/访客(0)。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    if user.is_superuser:
        return 3
    if user.is_staff:
        return 2
    if is_verified(user):
        return 1
    return 0


def can_manage_validity_for(actor, target):
    """actor 能否修改 target 的有效期（ADR-0041）。

    双条件：actor 持 ``accounts.manage_validity``，且 target 层级严格更低（下位）。
    平级 / 上位拒绝；超级管理员本身豁免且无人可改（target.is_superuser 恒拒）。
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    if not actor.has_perm("accounts.manage_validity"):
        return False
    if target is None or not getattr(target, "pk", None):
        return False
    if target.is_superuser:
        return False
    return rank_of(actor) > rank_of(target)


def sync_appointment_channel(user):
    """后台委任通道（ADR-0013 + ADR-0041）：管理员或超级管理员 ⇒ approved 行；否则删行。

    委任是后台副作用，不是用户走通道，故不受站点「验证通道开/关」约束。
    ``identifier`` 记委任档（``superuser`` 优先于 ``staff``）。``verified_by`` 空（系统）。
    有效期：超管 null（永久）；管理员 = 委任日 + 管理员有效期；仅在「未设 / 已过期」时
    重算（即首次授予或过期后重新授予），不因无关的 user.save 顺延。
    """
    if user is None or not getattr(user, "pk", None):
        return
    appointed = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    if not appointed:
        Verification.objects.filter(
            user=user, channel=Verification.CHANNEL_APPOINTMENT,
        ).delete()
        return

    ident = "superuser" if user.is_superuser else "staff"
    now = timezone.now()
    expires_at = None if user.is_superuser else (now + timedelta(days=admin_valid_days()))
    row, created = Verification.objects.get_or_create(
        user=user,
        channel=Verification.CHANNEL_APPOINTMENT,
        defaults={
            "status": Verification.STATUS_APPROVED,
            "identifier": ident,
            "verified_at": now,
            "expires_at": expires_at,
        },
    )
    if created:
        return
    fields = []
    if row.status != Verification.STATUS_APPROVED:
        row.status = Verification.STATUS_APPROVED
        fields.append("status")
    if row.identifier != ident:
        row.identifier = ident
        fields.append("identifier")
    if row.verified_at is None:
        row.verified_at = now
        fields.append("verified_at")
    if expires_at is None:
        if row.expires_at is not None:
            row.expires_at = None
            fields.append("expires_at")
    else:
        if row.expires_at is None or row.expires_at <= now:
            row.expires_at = expires_at
            fields.append("expires_at")
    if fields:
        row.save(update_fields=fields)


def verified_member_count():
    """已验证成员数（任一未过期 approved 通道的活跃用户）——众议「全员投完即结算」的分母。

    distinct：一个用户可能有多条 approved 通道，按用户去重。后台委任会使管理员/超管计入
    （他们有 appointment 行）；本函数不另读 ``is_staff`` / ``is_superuser``。
    """
    return (
        User.objects.filter(is_active=True, verifications__status=Verification.STATUS_APPROVED)
        .filter(
            models.Q(verifications__expires_at__isnull=True)
            | models.Q(verifications__expires_at__gt=timezone.now())
        )
        .distinct()
        .count()
    )


class IdentityProof(models.Model):
    """身份证明材料（学生证照片等）——审计留底，永久保存（审核通过后也不删）。

    与「附件」子系统隔离：附件绑定单一父级并随父级回收（ADR 0002）；身份证明无父级、
    供事后追溯。文件存 PRIVATE_MEDIA_ROOT 私有存储，仅本人或持 can_review_identity 者可读。
    """

    user = models.ForeignKey(
        User, verbose_name="用户", on_delete=models.CASCADE, related_name="identity_proofs"
    )
    file = models.ImageField(
        "证明材料", upload_to=identity_proof_upload_path, storage=private_media_storage
    )
    uploaded_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        verbose_name = "身份证明"
        verbose_name_plural = "身份证明"
        ordering = ["-uploaded_at"]
        permissions = [
            ("can_review_identity", "可以审核身份证明材料"),
        ]

    def __str__(self):
        return f"{self.user.username} 的身份证明 ({self.uploaded_at:%Y-%m-%d})"


class UserSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_sessions")
    session_key = models.CharField(max_length=40, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    device_type = models.CharField(max_length=16, default="Unknown")
    device_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["user", "is_current"])]
        ordering = ["-created_at"]

    def __str__(self):
        state = "current" if self.is_current else "old"
        return f"{self.user.username} @ {self.session_key[:8]} ({state})"


class AuthCode(models.Model):
    """认证码（ADR-0020）：后台生成、成员兑换即通过；有效期 × 可用次数。

    归属验证体系：兑换直接写 authcode 通道 approved（identifier=码原文，后台可读）。
    码的寿命（过期 / 吊销 / 用尽）只停止**后续**兑换，**不回溯**已通过者；兑换记录
    （AuthCodeRedemption）为审计留底。生成侧只在 Django 后台（不建前端管理页）。
    """

    code = models.CharField("认证码", max_length=32, unique=True)  # 12 位模板，存归一化大写
    note = models.CharField("备注", max_length=200, blank=True, default="")  # 发给谁 / 用途
    created_by = models.ForeignKey(
        User, verbose_name="生成人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="authcodes_created",
    )
    created_at = models.DateTimeField("生成时间", auto_now_add=True)
    expires_at = models.DateTimeField("有效期至")  # 必填：过期后不可兑换
    max_uses = models.PositiveIntegerField("可用次数", default=1)  # 可供多少个账号各用一次
    used_count = models.PositiveIntegerField("已用次数", default=0)
    revoked_at = models.DateTimeField("吊销时间", null=True, blank=True)  # 软吊销（留底）

    class Meta:
        verbose_name = "认证码"
        verbose_name_plural = "认证码"
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def status(self):
        """派生状态（不落库）：valid / expired / exhausted / revoked。

        优先级：吊销 > 过期 > 用尽 > 有效。过期纯惰性判定（后台展示 + 兑换时校验），
        无定时任务。
        """
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return "expired"
        if self.used_count >= self.max_uses:
            return "exhausted"
        return "valid"


class AuthCodeRedemption(models.Model):
    """兑换记录（审计留底）：一码一账号一条；同一账号可因「重新认证」多次兑换不同码。

    ADR-0041：认证过期后需重新认证，故约束由「每账号一条」放宽为「每 (账号, 码) 一条」——
    同一账号可先后兑换不同码（每次过期后重新认证留痕），但不可重复兑换同一码。
    """

    authcode = models.ForeignKey(
        AuthCode, verbose_name="认证码", on_delete=models.CASCADE, related_name="redemptions"
    )
    user = models.ForeignKey(
        User, verbose_name="用户", on_delete=models.CASCADE, related_name="authcode_redemptions"
    )
    redeemed_at = models.DateTimeField("兑换时间", auto_now_add=True)

    class Meta:
        verbose_name = "认证码兑换记录"
        verbose_name_plural = "认证码兑换记录"
        ordering = ["-redeemed_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "authcode"], name="unique_authcode_per_user_code"),
        ]

    def __str__(self):
        return f"{self.user.username} ← {self.authcode.code}"
