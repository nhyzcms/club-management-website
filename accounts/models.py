import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models import prefetch_related_objects
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


def password_reset_proof_upload_path(instance, filename):
    """密码重置申请的身份证明：同样落私有存储（仅申请人 / 审批人可读）。"""
    ext = os.path.splitext(filename)[1].lower()
    return f"password_reset_proofs/user_{instance.user_id}_{uuid.uuid4().hex}{ext}"


class Profile(models.Model):
    GENDER_CHOICES = [
        ("M", "男"),
        ("F", "女"),
        ("O", "其他"),
    ]
    # 需要登记「校牌号」的身份（注册页与资料校验共用；前端 types/profile.ts 镜像）：
    # 在校生 / 毕业生与社员名册相关，其余身份（外校生 / 家长 / 教师）不登记。
    CARD_NO_IDENTITIES = ("student", "graduate")
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
    # 时收集；identity 是纯元数据，不影响权限。认证态不在 Profile 上——见 Verification。
    real_name = models.CharField("真实姓名", max_length=100, blank=True)
    identity = models.CharField("身份", max_length=10, choices=IDENTITY_CHOICES, blank=True)

    # 校牌号（2026-10-23）：与名册行 MemberIdentity.card_no 是**同一个值**。
    # 在校生 / 毕业生可在注册时选填；名册里已导入时按「姓名 + 校牌号」唯一命中即自动绑定，
    # 否则先存这里，等名册导入后按姓名写回名册行（accounts.member_roster.sync_card_numbers）。
    # 名册有值时以名册为准（学校档案），两份始终对齐；绝不对外公开（校验页不下发）。
    card_no = models.CharField("校牌号", max_length=20, blank=True, default="")

    # 身份有效期（ADR-0041）：注册认证宽限覆盖 + 因超期停用标记。
    # registration_deadline 为 null = 按 date_joined + 站点「注册后认证宽限」起算；
    # 持 manage_validity 者可对下位用户显式延/缩。
    registration_deadline = models.DateTimeField("注册认证截止", null=True, blank=True)
    # expiry_disabled_at 标记「因注册超期未认证被系统停用」，用于登录时给专属提示；
    # 系统维护，不可手改。
    expiry_disabled_at = models.DateTimeField("因超期停用时间", null=True, blank=True)

    # 账号注销（自服务，ADR-0027）：非空 = 用户已主动注销。
    # 这是**软删除标记**——User / Profile 行本身永不删除：主键、用户名（账号唯一编码）、
    # 真实姓名、注册时间等留作后台审计与历史内容归属；敏感字段另行清除，
    # 见 accounts/deletion.py 与 messaging.serializers.SimpleUserSerializer（展示为「该用户已注销」）。
    deleted_at = models.DateTimeField("注销时间", null=True, blank=True)

    # 账号有效期一次性提示「已读」标记：存 ``accounts.validity_summary.account_validity()``
    # 生成的状态快照键（如 ``verified:2027-10-18T12:00:00+08:00``）。注册后 / 认证通过后
    # 前端弹窗展示到期时间与规则，点「我知道了」写回；键随状态或到期时间变化而失效，
    # 因而续期 / 重新认证后会再提示一次。
    validity_notice_ack = models.CharField(
        "有效期提示已读标记", max_length=80, blank=True, default="",
    )

    # 强制修改密码（管理员手动重置密码后置 True）：登录后除「改密 / 退出 / 读取会话」
    # 外的请求由 accounts.middleware.PasswordChangeRequiredMiddleware 拦下。
    # 用户自行改密成功或完成强制改密后清零。
    must_change_password = models.BooleanField("需强制修改密码", default=False)

    def __str__(self):
        return f"{self.user.username}'s profile"


class Verification(models.Model):
    """认证通道当前状态（ADR-0006）：每 (user, channel) 一行，in-place 更新。

    账号「已认证」⇔ 任一通道 ``status=approved`` 且未过期（见 :func:`is_verified`）。
    通道是一等公民：邮箱、人工审批、后台委任、认证码是通道；加通道 = 加 choices + 实现
    该通道流程，核心判定（任一 approved）不动。

    - ``identifier`` 是通道主体：邮箱=待认证地址（认证前住此、不进 ``User.email``）；人工=空；
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
    # 派生态（只在读取时计算，不落库、不进 STATUSES / choices）：
    # 账号已通过某通道认证后，其余通道一律视为「无需再次认证」，避免用户误以为
    # 还要把每个通道都走一遍（见 accounts.views.verification_status_view）。
    STATUS_NOT_REQUIRED = "not_required"
    STATUSES = [
        (STATUS_PENDING, "待认证"),
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
        verbose_name = "认证通道"
        verbose_name_plural = "认证通道"
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


# 已注销账号在所有公开展示位（私信发送者、新闻作者、评论作者……）的统一文案。
# 后端序列化层直接替换昵称，前端无需逐处判断（见 SimpleUserSerializer）。
DELETED_ACCOUNT_LABEL = "该用户已注销"


def is_deleted_user(user):
    """账号是否已注销：唯一真源是 ``Profile.deleted_at``。"""
    profile = profile_of(user)
    return bool(profile is not None and profile.deleted_at is not None)


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


def _prefetched_channels(user):
    """已预取 ``user.verifications`` 时返回内存里的通道行；未预取返回 None（走 SQL）。

    下面的判定函数都先问这里：有预取缓存就纯内存判定，否则退回原来的 ``.exists()``
    查询。两条路径语义逐字等价（同样的 status / channel / 有效期条件）。
    """
    cache = getattr(user, "_prefetched_objects_cache", None)
    if not cache or "verifications" not in cache:
        return None
    return list(user.verifications.all())


def prefetch_verifications_for(user):
    """把 ``user.verifications`` 一次读进内存，使本次请求后续的认证判定零 SQL。

    为什么需要它：列表序列化会对**同一行**反复判定「当前用户是否已认证」
    （活动列表的 ``owed``、收件箱的活动债），实测 20 行 = 20 条完全相同的通道查询。
    在取 queryset 前调一次本函数，这些判定就都走内存缓存。

    幂等：同一对象只预取一次（``prefetch_related_objects`` 重复调用会再查一次库）。
    安全性：预取缓存的生命周期只在这一个请求内，且调用点（列表 / 聚合视图）本身不写
    认证行；各认证通道的写路径照常直接查库，不会读到陈旧状态。返回原 user，便于链式写。
    """
    if user is None or not getattr(user, "pk", None):
        return user
    if getattr(user, "_verifications_prefetched", False):
        return user
    prefetch_related_objects([user], "verifications")
    user._verifications_prefetched = True
    return user


def has_ever_verified(user):
    """是否曾完成过任一认证（``verified_at`` 非空）。

    用于区分「从未认证」（适用注册 60 天宽限停用）与「认证后过期」（不适用该停用，
    只回落为访客、需重新认证）。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    rows = _prefetched_channels(user)
    if rows is not None:
        return any(row.verified_at is not None for row in rows)
    return user.verifications.filter(verified_at__isnull=False).exists()


def is_verified(user):
    """账号「已认证」单一计算源（ADR-0006 + ADR-0041）。

    任一认证通道 ``approved`` 且未过期即真。``expires_at=null`` 视为永久（超管委任 /
    后台显式延长）。过期通道不再算已认证，账号回落为访客、需重新认证。

    纯计算：不读 ``is_staff`` / ``is_superuser``（ADR-0013）。超管 / 管理员经后台委任通道
    计入（超管委任 expires_at=null 永久），不在本函数内特判标志位。权限轴逃生舱仍是
    ``has_perm`` 对超管恒真（ADR-0005 决策 9），不在本函数。

    热路径：调用方预取过 ``verifications``（见 :func:`prefetch_verifications_for`）时
    在内存判定，否则回到一次 ``EXISTS`` 查询。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    rows = _prefetched_channels(user)
    if rows is not None:
        now = timezone.now()
        return any(
            row.status == Verification.STATUS_APPROVED
            and (row.expires_at is None or row.expires_at > now)
            for row in rows
        )
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
    rows = _prefetched_channels(user)
    if rows is not None:
        now = timezone.now()
        return any(
            row.channel == Verification.CHANNEL_APPOINTMENT
            and row.status == Verification.STATUS_APPROVED
            and (row.expires_at is None or row.expires_at > now)
            for row in rows
        )
    return user.verifications.filter(
        channel=Verification.CHANNEL_APPOINTMENT,
        status=Verification.STATUS_APPROVED,
    ).filter(_unexpired_filter()).exists()


def rank_of(user):
    """权限层级：超级管理员(3) > 管理员(2) > 已认证用户(1) > 未认证/访客(0)。"""
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

    委任是后台副作用，不是用户走通道，故不受站点「认证通道开/关」约束。
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
    """已认证成员数（任一未过期 approved 通道的活跃用户）——众议「全员投完即结算」的分母。

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


class ValidityNotice(models.Model):
    """身份有效期预警的发送台账（幂等 + 审计）。

    通道 ``expires_at`` 到期会带来**降权**（认证通道：已认证 → 未认证；委任通道：撤销
    ``is_staff``），故在到期前两个月 / 一个月各发一次站内提醒，见 ``accounts.validity_notices``。

    唯一键含 **``expires_at`` 快照**：同一通道行换了到期时间（续期 / 过期后重新委任）
    自然重新起算，历史台账照旧留痕——只认通道行的话，续期后就再也发不出提醒了。
    """

    LEVEL_60D = "60d"
    LEVEL_30D = "30d"
    LEVELS = [
        (LEVEL_60D, "还剩两个月"),
        (LEVEL_30D, "还剩一个月"),
    ]

    verification = models.ForeignKey(
        Verification, verbose_name="认证通道", on_delete=models.CASCADE,
        related_name="validity_notices",
    )
    expires_at = models.DateTimeField("到期时间快照")
    level = models.CharField("档位", max_length=8, choices=LEVELS)
    sent_at = models.DateTimeField("发送时间", auto_now_add=True)

    class Meta:
        verbose_name = "身份有效期提醒"
        verbose_name_plural = "身份有效期提醒"
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["verification", "expires_at", "level"],
                name="unique_validity_notice_per_expiry_level",
            ),
        ]

    def __str__(self):
        return f"{self.verification_id} · {self.expires_at:%Y-%m-%d} · {self.level}"


class IdentityProof(models.Model):
    """身份证明材料（学生证照片等）——审计留底，默认长期保存（审核通过后也不删）。

    例外：账号**注销**时连同文件一并删除（ADR-0027）——注销即撤回对敏感材料的授权，
    不再保留审计证据。

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


class PasswordResetRequest(models.Model):
    """忘记密码 → 向管理员申请手动重置（登录页自助提交）。

    背景：邮箱找回依赖已认证邮箱；没有邮箱 / 邮箱已失效的社员无法自助重置。
    本流程让申请人上传身份证明，由持 ``accounts.review_password_reset`` 的管理员在
    审核台核对后批准：密码重置为 :data:`accounts.password_reset.DEFAULT_RESET_PASSWORD`
    并置 ``Profile.must_change_password``，强制下次登录改密。

    证明文件与身份证明一样落 **私有存储**（PRIVATE_MEDIA_ROOT），只经鉴权视图下发，
    绝不经公开 MEDIA_URL 暴露；账号注销时随 Profile 级联删除（见 accounts/deletion.py）。
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUSES = [
        (STATUS_PENDING, "待处理"),
        (STATUS_APPROVED, "已批准"),
        (STATUS_REJECTED, "已驳回"),
    ]

    user = models.ForeignKey(
        User, verbose_name="申请人", on_delete=models.CASCADE,
        related_name="password_reset_requests",
    )
    # 申请人填写的账号标识（用户名 / 邮箱），仅作审核时的对照信息。
    identifier = models.CharField("申请填写的账号", max_length=254, blank=True, default="")
    contact = models.CharField("联系方式", max_length=254, blank=True, default="")
    note = models.TextField("申请说明", blank=True, default="")
    proof = models.ImageField(
        "身份证明", upload_to=password_reset_proof_upload_path, storage=private_media_storage,
    )
    status = models.CharField("状态", max_length=10, choices=STATUSES, default=STATUS_PENDING)
    created_at = models.DateTimeField("提交时间", auto_now_add=True)
    # B2：审计三件套统一命名（原 reviewed_at / reviewed_by / review_note）
    moderated_at = models.DateTimeField("处理时间", null=True, blank=True)
    moderated_by = models.ForeignKey(
        User, verbose_name="处理人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="password_reset_reviews",
    )
    moderation_note = models.CharField("处理说明", max_length=200, blank=True, default="")
    reset_at = models.DateTimeField("密码重置时间", null=True, blank=True)

    class Meta:
        verbose_name = "密码重置申请"
        verbose_name_plural = "密码重置申请"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["user", "status"]),
        ]
        permissions = [
            ("review_password_reset", "可以审批密码重置申请"),
        ]

    def __str__(self):
        return f"{self.user.username} · 密码重置 · {self.get_status_display()}"


class AccountDevice(models.Model):
    """账号下的一台「设备」——由服务端签发的随机 device_id 标识（见 accounts/devices.py）。

    浏览器拿不到 MAC（无 API）；brand/model 是尽力推断，允许为空。设备是否「已知」
    （trusted_at 非空）只由「该设备上完成过一次二次验证」决定，不靠指纹推断。
    """

    user = models.ForeignKey(User, verbose_name="用户", on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField("设备 ID", max_length=64, db_index=True)
    label = models.CharField("设备名", max_length=128, blank=True, default="")
    browser = models.CharField("浏览器", max_length=64, blank=True, default="")
    platform = models.CharField("平台", max_length=32, blank=True, default="")
    brand = models.CharField("品牌", max_length=64, blank=True, default="")
    model = models.CharField("型号", max_length=96, blank=True, default="")
    mac_address = models.CharField(
        "MAC（浏览器不可得，预留给原生端）", max_length=32, blank=True, default=""
    )
    first_seen = models.DateTimeField("首次出现", auto_now_add=True)
    last_seen = models.DateTimeField("最近活跃", default=timezone.now)
    last_ip = models.GenericIPAddressField("最近 IP", null=True, blank=True)
    last_city = models.CharField("最近城市", max_length=64, blank=True, default="")
    last_country = models.CharField("最近国家/地区", max_length=64, blank=True, default="")
    trusted_at = models.DateTimeField("通过二次验证的时间", null=True, blank=True)
    revoked_at = models.DateTimeField("撤销时间", null=True, blank=True)

    class Meta:
        verbose_name = "账号设备"
        verbose_name_plural = "账号设备"
        ordering = ["-last_seen"]
        constraints = [
            models.UniqueConstraint(fields=["user", "device_id"], name="uniq_user_device"),
        ]
        indexes = [models.Index(fields=["user", "revoked_at"])]

    def __str__(self):
        return f"{self.user.username} · {self.label or self.device_id[-4:]}"

    @property
    def is_trusted(self) -> bool:
        return self.trusted_at is not None and self.revoked_at is None


class LoginEvent(models.Model):
    """登录事件流水：成功 / 失败 / 被限流 / 待二次验证都记。

    user 允许为空——撞库时账号可能不存在；此时只留 IP/UA 供风控分析。
    """

    STATUS_CHOICES = [
        ("success", "成功"),
        ("failed", "失败"),
        ("blocked", "被限流"),
        ("challenge", "待二次验证"),
    ]

    user = models.ForeignKey(
        User,
        verbose_name="用户",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_events",
    )
    device = models.ForeignKey(
        AccountDevice,
        verbose_name="设备",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_events",
    )
    session_key = models.CharField("会话键", max_length=40, blank=True, default="")
    method = models.CharField("登录方式", max_length=16, default="password")
    status = models.CharField("结果", max_length=16, choices=STATUS_CHOICES, default="success")
    second_factor = models.CharField("二次验证方式", max_length=16, blank=True, default="")
    is_new_device = models.BooleanField("新设备", default=False)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.TextField("User-Agent", blank=True, default="")
    city = models.CharField("城市", max_length=64, blank=True, default="")
    region = models.CharField("省份", max_length=64, blank=True, default="")
    country = models.CharField("国家/地区", max_length=64, blank=True, default="")
    latitude = models.FloatField("纬度（城市中心）", null=True, blank=True)
    longitude = models.FloatField("经度（城市中心）", null=True, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "登录事件"
        verbose_name_plural = "登录事件"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.user_id or '匿名'} {self.method}/{self.status} @ {self.created_at:%Y-%m-%d %H:%M}"


class TotpDevice(models.Model):
    """一台 TOTP 验证器（独立 secret，可绑定多台，上限见 accounts/totp.py）。"""

    user = models.ForeignKey(User, verbose_name="用户", on_delete=models.CASCADE, related_name="totp_devices")
    label = models.CharField("名称", max_length=64, blank=True, default="")
    secret_enc = models.CharField("密钥（Fernet 加密）", max_length=255)
    confirmed_at = models.DateTimeField("确认时间", null=True, blank=True)
    last_used_step = models.BigIntegerField("最后使用的时间步", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "滚动密钥"
        verbose_name_plural = "滚动密钥"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} · {self.label or 'TOTP'}"


class RecoveryCode(models.Model):
    """一次性恢复代码（只存 hash；明文仅在生成时展示一次）。"""

    user = models.ForeignKey(User, verbose_name="用户", on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField("代码哈希", max_length=64)
    used_at = models.DateTimeField("使用时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "恢复代码"
        verbose_name_plural = "恢复代码"
        ordering = ["-created_at"]


class LoginChallenge(models.Model):
    """陌生设备登录的中断态：密码已对，但设备未通过过二次验证。

    TTL 10 分钟、最多 5 次失败；通过后建 session 并把设备标记为 trusted。
    """

    user = models.ForeignKey(User, verbose_name="用户", on_delete=models.CASCADE, related_name="login_challenges")
    token = models.CharField("令牌", max_length=64, unique=True)
    device_id = models.CharField("设备 ID", max_length=64)
    methods = models.JSONField("可用验证方式", default=list)
    remember = models.BooleanField("记住登录", default=False)
    attempts = models.IntegerField("失败次数", default=0)
    expires_at = models.DateTimeField("过期时间")
    consumed_at = models.DateTimeField("完成时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "登录挑战"
        verbose_name_plural = "登录挑战"
        ordering = ["-created_at"]


class AdminAccessLog(models.Model):
    """管理端查看社员登录记录 / 设备的留痕（谁看了谁、何时、从哪）。"""

    actor = models.ForeignKey(User, verbose_name="操作者", on_delete=models.CASCADE, related_name="admin_access_logs")
    target = models.ForeignKey(
        User, verbose_name="被查看账号", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="admin_access_received",
    )
    scope = models.CharField("范围", max_length=32)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "管理端访问记录"
        verbose_name_plural = "管理端访问记录"
        ordering = ["-created_at"]


class UserSession(models.Model):
    """登录设备（多端登录，ADR-0028）。

    一行 = 一台设备上的一个会话。**唯一真源是 ``revoked_at``**：

    * ``revoked_at IS NULL`` —— 该设备仍保持登录态（在线），普通请求放行；
    * ``revoked_at`` 非空 —— 已被顶替 / 手动下线 / 安全吊销，只留历史记录，
      该设备的下一请求被中间件判 401 ``session_superseded``（浏览器导航给 HTML 页）。

    同一账号最多 ``MAX_ACTIVE_SESSIONS``（默认 3）个在线会话。第 4 台登录时由
    ``accounts.utils.record_user_session`` 顶掉「最久未活动」的那台（全局名额，
    不区分客户端类型：网页 / 手机浏览器 / App 天然各占一个）。
    """

    REVOKE_LIMIT = "limit"        # 名额已满，被新设备顶替
    REVOKE_MANUAL = "manual"      # 在个人中心被本人下线
    REVOKE_LOGOUT = "logout"      # 本机主动退出登录
    REVOKE_REPLACED = "replaced"  # 同一设备重新登录 / 改密轮换 session key
    REVOKE_SECURITY = "security"  # 安全事件（停用 / 重置密码 / 注销 / 撤销认证）
    REVOKE_REASONS = (
        (REVOKE_LIMIT, "名额顶替"),
        (REVOKE_MANUAL, "手动下线"),
        (REVOKE_LOGOUT, "主动退出"),
        (REVOKE_REPLACED, "设备重登"),
        (REVOKE_SECURITY, "安全吊销"),
    )

    CLIENT_KINDS = (
        ("web", "网页"),
        ("mobile", "手机浏览器"),
        ("app", "App"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_sessions")
    session_key = models.CharField(max_length=40, db_index=True)
    # 设备标识（俱乐部 `club_device` Cookie）：同一台设备重新登录时复用它的名额。
    # 长度与 ``AccountDevice.device_id`` 对齐到 64（2026-10）：两处曾分别是 40 / 64，
    # 现值由 ``secrets.token_hex(16)`` 生成（32 位）所以没触雷，但两处定义不一致
    # 迟早会在换生成算法或接原生端时炸掉——一处截断、另一处完整，认不出是同一台。
    device_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    client_kind = models.CharField(max_length=8, blank=True, default="web")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    device_type = models.CharField(max_length=16, default="Unknown")
    device_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=16, blank=True, default="")
    # 顶替本会话的那台设备的 session_key（用于「接管设备」提示）
    replaced_by_session_key = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["user", "revoked_at"])]
        ordering = ["-created_at", "-id"]

    def __str__(self):
        state = "active" if self.revoked_at is None else f"revoked:{self.revoked_reason}"
        return f"{self.user.username} @ {self.session_key[:8]} ({state})"

    @property
    def is_active(self):
        """是否仍保持登录态（``revoked_at`` 为空的派生值，不落库）。"""
        return self.revoked_at is None


class AuthCode(models.Model):
    """认证码（ADR-0020）：后台生成、成员兑换即通过；有效期 × 可用次数。

    归属认证体系：兑换直接写 authcode 通道 approved（identifier=码原文，后台可读）。
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


class IdentityImportBatch(models.Model):
    """名册导入批次（审计）：每次「确认导入」一行，附统计摘要。"""

    file_name = models.CharField("文件名", max_length=255)
    uploaded_by = models.ForeignKey(
        User, verbose_name="操作人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="identity_import_batches",
    )
    uploaded_at = models.DateTimeField("导入时间", auto_now_add=True)
    summary = models.JSONField("统计摘要", default=dict, blank=True)

    class Meta:
        verbose_name = "名册导入批次"
        verbose_name_plural = "名册导入批次"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.file_name} @ {self.uploaded_at:%Y-%m-%d %H:%M}"


class MemberIdentity(models.Model):
    """社员身份：一届名册中的一行（工牌识别码本体，ADR-0025）。

    - ``code`` 识别码全库唯一：一律按规则自动生成（表格「识别码」列内容忽略）；
    - ``user`` 绑定的站内账号（OneToOne，未绑 = null，多行 null 不冲突）。
      绑定三条路径：导入自动匹配（真实姓名唯一命中）/ 管理员手动 / 用户自助认领；
    - ``phone`` 仅后台可见，只用于认领校验（后四位），绝不在校验页等公开面出现。
    """

    STATUS_ACTIVE = "active"
    STATUS_GRADUATED = "graduated"
    STATUS_LEFT = "left"
    STATUSES = [
        (STATUS_ACTIVE, "在册"),
        (STATUS_GRADUATED, "已毕业"),
        (STATUS_LEFT, "已退社"),
    ]

    BIND_AUTO = "auto"
    BIND_ADMIN = "admin"
    BIND_SELF = "self"
    BIND_REGISTER = "register"
    BIND_METHODS = [
        (BIND_AUTO, "自动匹配"),
        (BIND_ADMIN, "管理员绑定"),
        (BIND_SELF, "自助认领"),
        (BIND_REGISTER, "注册时匹配"),
    ]

    # ---- 名册快照 ----
    # 注：不存「年级」——年级每年变动，快照一年后必失真；需要时按 admit_year 推算。
    name = models.CharField("姓名", max_length=100)
    class_no = models.CharField("班级", max_length=20, blank=True, default="")
    card_no = models.CharField("校牌号", max_length=20, blank=True, default="")
    admit_year = models.PositiveIntegerField("入学年份")
    joined_on_raw = models.CharField("入社时间", max_length=20, blank=True, default="")
    cohort = models.PositiveIntegerField("届数")
    gender = models.CharField("性别", max_length=8, blank=True, default="")
    phone = models.CharField("电话号码", max_length=20, blank=True, default="")

    # ---- 编号与绑定 ----
    code = models.CharField("识别码", max_length=16, unique=True)
    status = models.CharField("状态", max_length=12, choices=STATUSES, default=STATUS_ACTIVE)
    user = models.OneToOneField(
        User, verbose_name="绑定账号", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="member_identity",
    )
    bound_at = models.DateTimeField("绑定时间", null=True, blank=True)
    bound_by = models.ForeignKey(
        User, verbose_name="绑定操作人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="member_identities_bound",
    )
    bind_method = models.CharField("绑定方式", max_length=8, choices=BIND_METHODS, blank=True, default="")
    import_batch = models.ForeignKey(
        IdentityImportBatch, verbose_name="来源批次", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="identities",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "社员身份"
        verbose_name_plural = "社员身份"
        ordering = ["cohort", "code"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["cohort"]),
        ]
        permissions = [
            ("manage_member_roster", "可以管理社员名册（导入 / 绑定 / 导出）"),
        ]

    def __str__(self):
        return f"{self.name} · {self.cohort}届 · {self.code}"


# ---- 安全验证（Step-up，ADR-0026）----

class SecurityQuestion(models.Model):
    """安全问题（安全验证方式①）：预设题库、答案哈希（make_password）；每账号 1–3 条。"""

    user = models.ForeignKey(
        User, verbose_name="账号", on_delete=models.CASCADE, related_name="security_questions",
    )
    question_key = models.CharField("题库键", max_length=40)
    question_text = models.CharField("题干快照", max_length=200)
    answer_hash = models.CharField("答案哈希", max_length=128)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "安全问题"
        verbose_name_plural = "安全问题"
        ordering = ["user", "id"]

    def __str__(self):
        return f"{self.user_id} · {self.question_text}"


class StepUpEmailCode(models.Model):
    """邮箱验证码（安全验证方式②）：6 位、一次性、哈希存储、限试 5 次、TTL 10 分钟。"""

    user = models.ForeignKey(
        User, verbose_name="账号", on_delete=models.CASCADE, related_name="stepup_email_codes",
    )
    code_hash = models.CharField("验证码哈希", max_length=128)
    sent_to = models.CharField("发送至", max_length=254)
    expires_at = models.DateTimeField("有效期至")
    attempts = models.PositiveSmallIntegerField("已尝试次数", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    used_at = models.DateTimeField("使用时间", null=True, blank=True)

    class Meta:
        verbose_name = "安全验证码"
        verbose_name_plural = "安全验证码"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} · {self.sent_to} · {self.created_at:%Y-%m-%d %H:%M}"


class StepUpEvent(models.Model):
    """安全验证审计（轻量）：谁 / 何时 / 哪种方式 / 成败 / IP。"""

    user = models.ForeignKey(
        User, verbose_name="账号", on_delete=models.CASCADE, related_name="stepup_events",
    )
    scope = models.CharField("作用域", max_length=40)
    method = models.CharField("验证方式", max_length=16)  # email / question
    result = models.CharField("结果", max_length=16)  # ok / fail
    ip = models.CharField("IP", max_length=45, null=True, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True)

    class Meta:
        verbose_name = "安全验证记录"
        verbose_name_plural = "安全验证记录"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} · {self.scope} · {self.method} · {self.result}"
