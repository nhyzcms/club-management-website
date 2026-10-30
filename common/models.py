from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .policy import (
    DEFAULT_ADMIN_VALID_DAYS,
    DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR,
    DEFAULT_AUTO_UPDATE_ENABLED,
    DEFAULT_COMMENT_MAX_DEPTH,
    DEFAULT_COMMENTS_ENABLED,
    DEFAULT_CONTENT_REVIEW_ENABLED,
    DEFAULT_DMS_ENABLED,
    DEFAULT_FEEDBACK_ANON_PER_IP_PER_DAY,
    DEFAULT_REGISTRATION_VERIFY_DAYS,
    DEFAULT_REPORTS_PER_USER_PER_DAY,
    DEFAULT_LOGIN_PER_IP_PER_HOUR,
    DEFAULT_LOGIN_PER_USERNAME_PER_HOUR,
    DEFAULT_MEMBER_CHECK_PER_IP_PER_HOUR,
    DEFAULT_MEMBER_LOOKUP_PER_IP_PER_HOUR,
    DEFAULT_MEMBER_CLAIM_ENABLED,
    DEFAULT_MEMBER_CLAIM_PER_IP_PER_DAY,
    DEFAULT_MEMBER_CLAIM_PER_USER_PER_HOUR,
    DEFAULT_STEPUP_EMAIL_PER_IP_PER_HOUR,
    DEFAULT_STEPUP_EMAIL_PER_USER_PER_HOUR,
    DEFAULT_REGISTER_PER_IP_PER_DAY,
    DEFAULT_REGISTRATION_ENABLED,
    DEFAULT_RESEND_VERIFICATION_PER_IP_PER_HOUR,
    DEFAULT_SYNC_UPLOAD_MAX_BYTES,
    DEFAULT_TUS_MEDIA_MAX_BYTES,
    DEFAULT_UPDATE_APPLY_CUTOFF_MINUTES_BEFORE_END,
    DEFAULT_UPDATE_DB_BACKUP_KEEP,
    DEFAULT_UPDATE_POLL_INTERVAL_SECONDS,
    DEFAULT_UPDATE_RELEASE_KEEP,
    DEFAULT_UPDATE_TIMEZONE,
    DEFAULT_UPDATE_WINDOW_END_HOUR,
    DEFAULT_UPDATE_WINDOW_START_HOUR,
    DEFAULT_VERIFICATION_ENABLED,
    DEFAULT_VERIFICATION_VALID_DAYS,
    invalidate_policy_cache,
)

_HOUR_VALIDATORS = [MinValueValidator(0), MaxValueValidator(23)]


class Tag(models.Model):
    """标签（跨模块公共概念：新闻与任务共用）。

    原属 ``tasks``，2026-10 移到 ``common``（B7）：``news.News.tags`` 一直
    引用 ``tasks.Tag``，等于「新闻依赖任务」——一个纯展示模块为了标签
    拖进整个任务域。GitHub 上这类东西也不会挂在某个业务模块下。

    ``db_table`` 写死旧表名：迁移是纯状态搬运，**零 DDL**、数据不动。
    权限 codename 的 app_label 由 ``tasks`` 变 ``common``，既有授权由
    ``common/0014_copy_tag_permission`` 复制过去（旧权限行保留，不再读取）。
    """

    name = models.CharField("名称", max_length=50, unique=True)
    color = models.CharField("颜色", max_length=7, default="#007bff")

    class Meta:
        db_table = "tasks_tag"
        verbose_name = "标签"
        verbose_name_plural = "标签"
        ordering = ["name"]
        permissions = [
            ("manage_tags", "可管理标签"),
        ]

    def __str__(self):
        return self.name


class ContentTarget(models.Model):
    """「可被评论 / 审核 / 举报 / 挂附件的对象」的统一锚点。

    ## 为什么需要它

    在此之前，同一个概念被实现了四遍：``Attachment`` 用 5 个可空外键、
    ``Review`` 3 个、``ReportCase`` 5 个、``CommentThread`` 3 个，每张表再配一条
    2^n 项的 ``CheckConstraint`` 保证「恰好挂在一个父级上」。

    代价不是代码丑，是**加一种可评论的东西要改四张表**：加列、重写约束、
    改所有 queryset 与序列化器。而且每加一种宿主，约束的项数就翻一倍。

    ## 形态

    ``(kind, object_id)`` 唯一标识一个对象。宿主模型删除时由
    ``common/targets.py`` 的信号删掉这条 target，``CASCADE`` 会带走挂在它上面的
    附件 / 审核 / 举报 / 评论区。

    新增一种宿主 = ``KIND_CHOICES`` 加一项 + ``targets.KIND_TO_MODEL`` 加一行，
    **零 DDL**。

    ## 为什么不给 object_id 加外键

    它指向 8 张不同的表。要拿到数据库级外键完整性，就得在每张宿主表上各加一个
    反向 OneToOne——那是再改 8 张表，换来的只是「防止信号漏接」。代价不对等。
    孤儿 target 由 ``prune_orphan_targets`` 管理命令兜底（B9）。
    """

    KIND_NEWS = "news"
    KIND_ACTIVITY = "activity"
    KIND_TUTORIAL = "tutorial"
    KIND_TASK = "task"
    KIND_COMMENT = "comment"
    KIND_SUBMISSION = "submission"
    KIND_EXHIBIT = "exhibit"
    KIND_FEEDBACK = "feedback"
    KIND_CHOICES = [
        (KIND_NEWS, "新闻"),
        (KIND_ACTIVITY, "活动"),
        (KIND_TUTORIAL, "教程"),
        (KIND_TASK, "任务"),
        (KIND_COMMENT, "评论"),
        (KIND_SUBMISSION, "作品"),
        (KIND_EXHIBIT, "展品"),
        (KIND_FEEDBACK, "意见反馈"),
    ]

    kind = models.CharField("类型", max_length=20, choices=KIND_CHOICES)
    object_id = models.PositiveBigIntegerField("对象 ID")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "内容目标"
        verbose_name_plural = "内容目标"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "object_id"], name="uniq_content_target",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}#{self.object_id}"


class SiteSettings(models.Model):
    """Singleton operational knobs (pk always 1). Edit in Django admin."""

    verification_enabled = models.BooleanField(
        "认证通道开启",
        default=DEFAULT_VERIFICATION_ENABLED,
        help_text="关闭后不可新开或完成任何认证通道；已通过者仍算已认证。",
    )
    verification_valid_days = models.PositiveIntegerField(
        "认证有效期（天）",
        default=DEFAULT_VERIFICATION_VALID_DAYS,
        validators=[MinValueValidator(1)],
        help_text="认证码 / 人工核验 / 邮箱认证通过后，认证状态的有效天数；过期需重新认证。",
    )
    admin_valid_days = models.PositiveIntegerField(
        "管理员身份有效期（天）",
        default=DEFAULT_ADMIN_VALID_DAYS,
        validators=[MinValueValidator(1)],
        help_text="管理员身份自授予之日起的有效天数；过期需重新授予。超级管理员不受限。",
    )
    registration_verify_days = models.PositiveIntegerField(
        "注册后认证宽限（天）",
        default=DEFAULT_REGISTRATION_VERIFY_DAYS,
        validators=[MinValueValidator(1)],
        help_text="注册后未完成认证的宽限天数；超期将停用该账号。",
    )
    content_review_enabled = models.BooleanField(
        "开启内容审核",
        default=DEFAULT_CONTENT_REVIEW_ENABLED,
        help_text="关闭后新建新闻、活动、教程直接通过，不进待审队列；已有待审条目不会批量通过。",
    )
    registration_enabled = models.BooleanField(
        "开放自助注册",
        default=DEFAULT_REGISTRATION_ENABLED,
        help_text="关闭后自助注册接口返回 403。",
    )
    register_per_ip_per_day = models.PositiveIntegerField(
        "每 IP 每日注册次数",
        default=DEFAULT_REGISTER_PER_IP_PER_DAY,
    )
    resend_verification_per_ip_per_hour = models.PositiveIntegerField(
        "每 IP 每小时重发认证邮件次数",
        default=DEFAULT_RESEND_VERIFICATION_PER_IP_PER_HOUR,
    )
    login_per_ip_per_hour = models.PositiveIntegerField(
        "每 IP 每小时登录失败次数",
        default=DEFAULT_LOGIN_PER_IP_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="门户登录与 Django admin 登录共用。只计失败，成功登录不占额度。",
    )
    login_per_username_per_hour = models.PositiveIntegerField(
        "每用户名每小时登录失败次数",
        default=DEFAULT_LOGIN_PER_USERNAME_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="按用户名或邮箱计，防针对单一账号的撞库。",
    )
    feedback_anon_per_ip_per_day = models.PositiveIntegerField(
        "每 IP 每日匿名反馈次数",
        default=DEFAULT_FEEDBACK_ANON_PER_IP_PER_DAY,
    )
    reports_per_user_per_day = models.PositiveIntegerField(
        "每用户每日举报次数",
        default=DEFAULT_REPORTS_PER_USER_PER_DAY,
        validators=[MinValueValidator(1)],
        help_text="已认证成员提交举报的日上限。",
    )
    authcode_redeem_per_user_per_hour = models.PositiveIntegerField(
        "每账号每小时认证码兑换失败次数",
        default=DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="认证码兑换只计失败；成功兑换不占额度。",
    )
    member_claim_enabled = models.BooleanField(
        "开放社员身份自助认领",
        default=DEFAULT_MEMBER_CLAIM_ENABLED,
        help_text="关闭后：认领接口 403、注册后的认领阶段不展示；已绑定关系不受影响。",
    )
    member_claim_per_user_per_hour = models.PositiveIntegerField(
        "每账号每小时认领失败次数",
        default=DEFAULT_MEMBER_CLAIM_PER_USER_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="自助认领只计失败；成功认领不占额度。",
    )
    member_claim_per_ip_per_day = models.PositiveIntegerField(
        "每 IP 每日认领失败次数",
        default=DEFAULT_MEMBER_CLAIM_PER_IP_PER_DAY,
        validators=[MinValueValidator(1)],
    )
    member_check_per_ip_per_hour = models.PositiveIntegerField(
        "每 IP 每小时扫码校验次数",
        default=DEFAULT_MEMBER_CHECK_PER_IP_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="工牌二维码校验的公开端点频控（计全部请求）。",
    )
    member_lookup_per_ip_per_hour = models.PositiveIntegerField(
        "每 IP 每小时条码载荷查询次数",
        default=DEFAULT_MEMBER_LOOKUP_PER_IP_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="12 位条码载荷的匿名查询频控；现场连续核对需要比二维码校验更宽。",
    )
    stepup_email_per_user_per_hour = models.PositiveIntegerField(
        "安全验证：每账号每小时验证码次数",
        default=DEFAULT_STEPUP_EMAIL_PER_USER_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="安全验证邮箱验证码的每小时上限（按账号）。",
    )
    stepup_email_per_ip_per_hour = models.PositiveIntegerField(
        "安全验证：每 IP 每小时验证码次数",
        default=DEFAULT_STEPUP_EMAIL_PER_IP_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="安全验证邮箱验证码的每小时上限（按 IP）。",
    )
    sync_upload_max_bytes = models.PositiveBigIntegerField(
        "同步上传单文件上限（字节）",
        default=DEFAULT_SYNC_UPLOAD_MAX_BYTES,
        help_text="任意类型走同步通路的上限；超过则仅图片/视频可走 tus。",
    )
    tus_media_max_bytes = models.PositiveBigIntegerField(
        "tus 图/视频上限（字节）",
        default=DEFAULT_TUS_MEDIA_MAX_BYTES,
    )
    auto_update_enabled = models.BooleanField(
        "开启自动更新",
        default=DEFAULT_AUTO_UPDATE_ENABLED,
        help_text="关闭后守护进程跳过下载与应用。",
    )
    update_poll_interval_seconds = models.PositiveIntegerField(
        "轮询间隔（秒）",
        default=DEFAULT_UPDATE_POLL_INTERVAL_SECONDS,
    )
    update_timezone = models.CharField(
        "更新时区",
        max_length=63,
        default=DEFAULT_UPDATE_TIMEZONE,
        help_text="IANA 时区名；不用 Django TIME_ZONE。",
    )
    update_window_start_hour = models.PositiveSmallIntegerField(
        "窗口开始时刻（时）",
        default=DEFAULT_UPDATE_WINDOW_START_HOUR,
        validators=_HOUR_VALIDATORS,
        help_text="应用窗口为 [开始, 结束) 的整点小时，时区见「更新时区」。",
    )
    update_window_end_hour = models.PositiveSmallIntegerField(
        "窗口结束时刻（时）",
        default=DEFAULT_UPDATE_WINDOW_END_HOUR,
        validators=_HOUR_VALIDATORS,
    )
    update_apply_cutoff_minutes_before_end = models.PositiveIntegerField(
        "窗口结束前截止分钟",
        default=DEFAULT_UPDATE_APPLY_CUTOFF_MINUTES_BEFORE_END,
        help_text="窗口结束前 N 分钟起不再开始应用更新。",
    )
    update_release_keep = models.PositiveIntegerField(
        "保留发行包份数",
        default=DEFAULT_UPDATE_RELEASE_KEEP,
    )
    update_db_backup_keep = models.PositiveIntegerField(
        "保留数据库快照份数",
        default=DEFAULT_UPDATE_DB_BACKUP_KEEP,
    )
    comments_enabled = models.BooleanField(
        "启用评论区",
        default=DEFAULT_COMMENTS_ENABLED,
        help_text="关闭后前端不再显示评论区，且无法发表新评论；已有评论保留。",
    )
    comment_max_depth = models.PositiveSmallIntegerField(
        "评论最大嵌套深度",
        default=DEFAULT_COMMENT_MAX_DEPTH,
        validators=[MinValueValidator(1), MaxValueValidator(32)],
        help_text="1 表示仅允许根评论；超过则拒绝，不改挂。",
    )
    dms_enabled = models.BooleanField(
        "启用私信",
        default=DEFAULT_DMS_ENABLED,
        help_text="关闭后前端不再显示私信入口，且无法发起或发送私信；已有会话保留。",
    )

    class Meta:
        verbose_name = "站点策略"
        verbose_name_plural = "站点策略"

    def __str__(self):
        return "站点策略"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        invalidate_policy_cache()

    def delete(self, *args, **kwargs):
        return 0, {}
