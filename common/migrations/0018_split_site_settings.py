"""把 SiteSettings 的 33 个字段拆到五张领域表（B5 PR 1）。

## 为什么拆

一张表 33 个字段，横跨认证、频控、上传、自动更新、内容五个互不相干的领域。
admin 里是一个 33 输入框的表单：改上传上限要连带提交全部字段，两个人同时编辑
不同领域会互相覆盖。

## 为什么 PR 1 不删 SiteSettings

双读期。本迁移只负责「建表 + 搬数据」，`get_policy()` 已改成读五张表；旧表留着
给回滚用，PR 2 确认无碍后再删。

反向迁移把五张表合并回 SiteSettings——**这是回滚的唯一依靠**，没有它回滚后
策略全部回到默认值，线上频控会突然变松。

## 搬运是 update_or_create(pk=1)

五张表都是 singleton。历史模型没有自定义 `save()`，不会被强制改 pk。
"""

import django.core.validators
from django.db import migrations, models

GROUP_FIELDS = {
    "AuthPolicy": [
        "verification_enabled", "verification_valid_days", "admin_valid_days",
        "registration_verify_days", "registration_enabled", "member_claim_enabled",
    ],
    "RateLimitPolicy": [
        "register_per_ip_per_day", "resend_verification_per_ip_per_hour",
        "login_per_ip_per_hour", "login_per_username_per_hour",
        "feedback_anon_per_ip_per_day", "reports_per_user_per_day",
        "authcode_redeem_per_user_per_hour", "member_claim_per_user_per_hour",
        "member_claim_per_ip_per_day", "member_check_per_ip_per_hour",
        "member_lookup_per_ip_per_hour", "stepup_email_per_user_per_hour",
        "stepup_email_per_ip_per_hour",
    ],
    "UploadPolicy": ["sync_upload_max_bytes", "tus_media_max_bytes"],
    "UpdaterPolicy": [
        "auto_update_enabled", "update_poll_interval_seconds", "update_timezone",
        "update_window_start_hour", "update_window_end_hour",
        "update_apply_cutoff_minutes_before_end", "update_release_keep",
        "update_db_backup_keep",
    ],
    "ContentPolicy": [
        "content_review_enabled", "comments_enabled", "comment_max_depth", "dms_enabled",
    ],
}


def copy_from_settings(apps, schema_editor):
    """把 SiteSettings 那唯一一行拆到五张表。"""
    SiteSettings = apps.get_model("common", "SiteSettings")
    src = SiteSettings.objects.filter(pk=1).first()
    if src is None:
        return
    for model_name, fields in GROUP_FIELDS.items():
        model = apps.get_model("common", model_name)
        model.objects.update_or_create(
            pk=1, defaults={f: getattr(src, f) for f in fields},
        )


def copy_back(apps, schema_editor):
    """反向：五张表合并回 SiteSettings（PR 2 删表后回滚靠这个）。"""
    SiteSettings = apps.get_model("common", "SiteSettings")
    if not SiteSettings.objects.filter(pk=1).exists():
        return
    merged = {}
    for model_name, fields in GROUP_FIELDS.items():
        model = apps.get_model("common", model_name)
        row = model.objects.filter(pk=1).first()
        if row is not None:
            merged.update({f: getattr(row, f) for f in fields})
    if merged:
        SiteSettings.objects.filter(pk=1).update(**merged)


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0017_backfill_content_targets'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('verification_enabled', models.BooleanField(default=True, help_text='关闭后不可新开或完成任何认证通道；已通过者仍算已认证。', verbose_name='认证通道开启')),
                ('verification_valid_days', models.PositiveIntegerField(default=365, help_text='认证码 / 人工核验 / 邮箱认证通过后，认证状态的有效天数；过期需重新认证。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='认证有效期（天）')),
                ('admin_valid_days', models.PositiveIntegerField(default=730, help_text='管理员身份自授予之日起的有效天数；过期需重新授予。超级管理员不受限。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='管理员身份有效期（天）')),
                ('registration_verify_days', models.PositiveIntegerField(default=60, help_text='注册后未完成认证的宽限天数；超期将停用该账号。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='注册后认证宽限（天）')),
                ('registration_enabled', models.BooleanField(default=True, help_text='关闭后自助注册接口返回 403。', verbose_name='开放自助注册')),
                ('member_claim_enabled', models.BooleanField(default=True, help_text='关闭后：认领接口 403、注册后的认领阶段不展示；已绑定关系不受影响。', verbose_name='开放社员身份自助认领')),
            ],
            options={
                'verbose_name': '认证策略',
                'verbose_name_plural': '认证策略',
            },
        ),
        migrations.CreateModel(
            name='ContentPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content_review_enabled', models.BooleanField(default=True, help_text='关闭后新建新闻、活动、教程直接通过，不进待审队列；已有待审条目不会批量通过。', verbose_name='开启内容审核')),
                ('comments_enabled', models.BooleanField(default=True, help_text='关闭后前端不再显示评论区，且无法发表新评论；已有评论保留。', verbose_name='启用评论区')),
                ('comment_max_depth', models.PositiveSmallIntegerField(default=8, help_text='1 表示仅允许根评论；超过则拒绝，不改挂。', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(32)], verbose_name='评论最大嵌套深度')),
                ('dms_enabled', models.BooleanField(default=True, help_text='关闭后前端不再显示私信入口，且无法发起或发送私信；已有会话保留。', verbose_name='启用私信')),
            ],
            options={
                'verbose_name': '内容策略',
                'verbose_name_plural': '内容策略',
            },
        ),
        migrations.CreateModel(
            name='RateLimitPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('register_per_ip_per_day', models.PositiveIntegerField(default=5, verbose_name='每 IP 每日注册次数')),
                ('resend_verification_per_ip_per_hour', models.PositiveIntegerField(default=5, verbose_name='每 IP 每小时重发认证邮件次数')),
                ('login_per_ip_per_hour', models.PositiveIntegerField(default=30, help_text='门户登录与 Django admin 登录共用。只计失败，成功登录不占额度。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='每 IP 每小时登录失败次数')),
                ('login_per_username_per_hour', models.PositiveIntegerField(default=10, help_text='按用户名或邮箱计，防针对单一账号的撞库。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='每用户名每小时登录失败次数')),
                ('feedback_anon_per_ip_per_day', models.PositiveIntegerField(default=10, verbose_name='每 IP 每日匿名反馈次数')),
                ('reports_per_user_per_day', models.PositiveIntegerField(default=10, help_text='已认证成员提交举报的日上限。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='每用户每日举报次数')),
                ('authcode_redeem_per_user_per_hour', models.PositiveIntegerField(default=10, help_text='认证码兑换只计失败；成功兑换不占额度。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='每账号每小时认证码兑换失败次数')),
                ('member_claim_per_user_per_hour', models.PositiveIntegerField(default=5, help_text='自助认领只计失败；成功认领不占额度。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='每账号每小时认领失败次数')),
                ('member_claim_per_ip_per_day', models.PositiveIntegerField(default=20, validators=[django.core.validators.MinValueValidator(1)], verbose_name='每 IP 每日认领失败次数')),
                ('member_check_per_ip_per_hour', models.PositiveIntegerField(default=60, help_text='工牌二维码校验的公开端点频控（计全部请求）。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='每 IP 每小时扫码校验次数')),
                ('member_lookup_per_ip_per_hour', models.PositiveIntegerField(default=300, help_text='12 位条码载荷的匿名查询频控；现场连续核对需要比二维码校验更宽。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='每 IP 每小时条码载荷查询次数')),
                ('stepup_email_per_user_per_hour', models.PositiveIntegerField(default=5, help_text='安全验证邮箱验证码的每小时上限（按账号）。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='安全验证：每账号每小时验证码次数')),
                ('stepup_email_per_ip_per_hour', models.PositiveIntegerField(default=10, help_text='安全验证邮箱验证码的每小时上限（按 IP）。', validators=[django.core.validators.MinValueValidator(1)], verbose_name='安全验证：每 IP 每小时验证码次数')),
            ],
            options={
                'verbose_name': '频控策略',
                'verbose_name_plural': '频控策略',
            },
        ),
        migrations.CreateModel(
            name='UpdaterPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('auto_update_enabled', models.BooleanField(default=True, help_text='关闭后守护进程跳过下载与应用。', verbose_name='开启自动更新')),
                ('update_poll_interval_seconds', models.PositiveIntegerField(default=900, verbose_name='轮询间隔（秒）')),
                ('update_timezone', models.CharField(default='Asia/Shanghai', help_text='IANA 时区名；不用 Django TIME_ZONE。', max_length=63, verbose_name='更新时区')),
                ('update_window_start_hour', models.PositiveSmallIntegerField(default=1, help_text='应用窗口为 [开始, 结束) 的整点小时，时区见「更新时区」。', validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(23)], verbose_name='窗口开始时刻（时）')),
                ('update_window_end_hour', models.PositiveSmallIntegerField(default=3, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(23)], verbose_name='窗口结束时刻（时）')),
                ('update_apply_cutoff_minutes_before_end', models.PositiveIntegerField(default=30, help_text='窗口结束前 N 分钟起不再开始应用更新。', verbose_name='窗口结束前截止分钟')),
                ('update_release_keep', models.PositiveIntegerField(default=3, verbose_name='保留发行包份数')),
                ('update_db_backup_keep', models.PositiveIntegerField(default=5, verbose_name='保留数据库快照份数')),
            ],
            options={
                'verbose_name': '更新策略',
                'verbose_name_plural': '更新策略',
            },
        ),
        migrations.CreateModel(
            name='UploadPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sync_upload_max_bytes', models.PositiveBigIntegerField(default=52428800, help_text='任意类型走同步通路的上限；超过则仅图片/视频可走 tus。', verbose_name='同步上传单文件上限（字节）')),
                ('tus_media_max_bytes', models.PositiveBigIntegerField(default=524288000, verbose_name='tus 图/视频上限（字节）')),
            ],
            options={
                'verbose_name': '上传策略',
                'verbose_name_plural': '上传策略',
            },
        ),
        # 必须排在五张 CreateModel 之后——那时表才存在
        migrations.RunPython(copy_from_settings, copy_back),
    ]
