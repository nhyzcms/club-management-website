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


class SiteSettings(models.Model):
    """Singleton operational knobs (pk always 1). Edit in Django admin."""

    verification_enabled = models.BooleanField(
        "验证通道开启",
        default=DEFAULT_VERIFICATION_ENABLED,
        help_text="关闭后不可新开或完成任何验证通道；已通过者仍算已验证。",
    )
    verification_valid_days = models.PositiveIntegerField(
        "认证有效期（天）",
        default=DEFAULT_VERIFICATION_VALID_DAYS,
        validators=[MinValueValidator(1)],
        help_text="认证码 / 人工核验 / 邮箱验证通过后，认证状态的有效天数；过期需重新认证。",
    )
    admin_valid_days = models.PositiveIntegerField(
        "管理员身份有效期（天）",
        default=DEFAULT_ADMIN_VALID_DAYS,
        validators=[MinValueValidator(1)],
        help_text="管理员身份自授予之日起的有效天数；过期需重新授予。超级管理员不受限。",
    )
    registration_verify_days = models.PositiveIntegerField(
        "注册后验证宽限（天）",
        default=DEFAULT_REGISTRATION_VERIFY_DAYS,
        validators=[MinValueValidator(1)],
        help_text="注册后未完成验证的宽限天数；超期将停用该账号。",
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
        "每 IP 每小时重发验证邮件次数",
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
        help_text="已验证成员提交举报的日上限。",
    )
    authcode_redeem_per_user_per_hour = models.PositiveIntegerField(
        "每账号每小时认证码兑换失败次数",
        default=DEFAULT_AUTHCODE_REDEEM_PER_USER_PER_HOUR,
        validators=[MinValueValidator(1)],
        help_text="认证码兑换只计失败；成功兑换不占额度。",
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
