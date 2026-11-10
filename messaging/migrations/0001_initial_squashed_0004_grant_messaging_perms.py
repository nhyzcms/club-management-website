"""Squash messaging 0001–0004.

New installs create the current comment/DM/notification schema with no
proposal FK. Existing databases that applied 0001–0004 skip this via
``replaces``.
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def backfill_threads(apps, schema_editor):
    CommentThread = apps.get_model("messaging", "CommentThread")
    News = apps.get_model("news", "News")
    Activity = apps.get_model("activities", "Activity")
    Task = apps.get_model("tasks", "Task")
    for news in News.objects.all().iterator():
        CommentThread.objects.get_or_create(news_id=news.pk, defaults={"status": "open"})
    for activity in Activity.objects.all().iterator():
        CommentThread.objects.get_or_create(activity_id=activity.pk, defaults={"status": "open"})
    for task in Task.objects.all().iterator():
        CommentThread.objects.get_or_create(task_id=task.pk, defaults={"status": "open"})


def grant(apps, schema_editor):
    from django.apps import apps as real_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for app_config in real_apps.get_app_configs():
        create_contenttypes(app_config, apps=apps, verbosity=0)
        create_permissions(app_config, apps=apps, verbosity=0)
    president, _ = Group.objects.get_or_create(name="社长")
    for codename in ("mute_user", "manage_comment_thread"):
        perm = Permission.objects.get(content_type__app_label="messaging", codename=codename)
        president.permissions.add(perm)
    info, _ = Group.objects.get_or_create(name="信息组")
    perm = Permission.objects.get(content_type__app_label="messaging", codename="manage_announcement")
    info.permissions.add(perm)


class Migration(migrations.Migration):

    initial = True

    replaces = [
        ("messaging", "0001_initial"),
        ("messaging", "0002_banner_remove_conversation_conversation_type_and_more"),
        ("messaging", "0003_backfill_comment_threads"),
        ("messaging", "0004_grant_messaging_perms"),
    ]

    dependencies = [
        ("accounts", "0002_seed_default_groups"),
        ("activities", "0013_questionnaire"),
        ("news", "0003_remove_news_category"),
        ("tasks", "0002_delete_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Conversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, max_length=200, verbose_name="标题")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("participants", models.ManyToManyField(related_name="conversations", to=settings.AUTH_USER_MODEL, verbose_name="参与者")),
            ],
            options={
                "verbose_name": "会话",
                "verbose_name_plural": "会话",
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content", models.TextField(verbose_name="内容")),
                ("retracted_at", models.DateTimeField(blank=True, null=True, verbose_name="撤回时间")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="messaging.conversation", verbose_name="会话")),
                ("mentions", models.ManyToManyField(blank=True, related_name="mentioned_in_messages", to=settings.AUTH_USER_MODEL, verbose_name="提及用户")),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sent_messages", to=settings.AUTH_USER_MODEL, verbose_name="发送者")),
            ],
            options={
                "verbose_name": "消息",
                "verbose_name_plural": "消息",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="MessageReadStatus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("read_at", models.DateTimeField(auto_now_add=True, verbose_name="已读时间")),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="read_statuses", to="messaging.message", verbose_name="消息")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="message_read_statuses", to=settings.AUTH_USER_MODEL, verbose_name="用户")),
            ],
            options={
                "verbose_name": "已读状态",
                "verbose_name_plural": "已读状态",
                "unique_together": {("message", "user")},
            },
        ),
        migrations.CreateModel(
            name="Banner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.TextField(verbose_name="正文")),
                ("link", models.CharField(blank=True, default="", max_length=500, verbose_name="链接")),
                ("starts_at", models.DateTimeField(verbose_name="开始时间")),
                ("ends_at", models.DateTimeField(verbose_name="结束时间")),
                ("priority", models.IntegerField(default=0, help_text="数值越大越优先；相同则较新者胜出。", verbose_name="优先级")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "横幅公告",
                "verbose_name_plural": "横幅公告",
                "ordering": ["-priority", "-created_at"],
                "permissions": [("manage_announcement", "管理横幅公告")],
            },
        ),
        migrations.CreateModel(
            name="CommentThread",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("open", "开放"), ("muted", "禁言"), ("closed", "关闭")], default="open", max_length=10, verbose_name="状态")),
                ("activity", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="comment_thread", to="activities.activity", verbose_name="活动")),
                ("news", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="comment_thread", to="news.news", verbose_name="新闻")),
                ("task", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="comment_thread", to="tasks.task", verbose_name="任务")),
            ],
            options={
                "verbose_name": "评论区",
                "verbose_name_plural": "评论区",
                "permissions": [("manage_comment_thread", "评论区协管")],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(activity__isnull=True, news__isnull=False, task__isnull=True)
                            | models.Q(activity__isnull=False, news__isnull=True, task__isnull=True)
                            | models.Q(activity__isnull=True, news__isnull=True, task__isnull=False)
                        ),
                        name="commentthread_exactly_one_parent",
                        violation_error_message="评论区必须且只能挂在一个宿主（新闻/活动/任务）上。",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Comment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content", models.TextField(verbose_name="内容")),
                ("retracted_at", models.DateTimeField(blank=True, null=True, verbose_name="撤回时间")),
                ("deleted_at", models.DateTimeField(blank=True, null=True, verbose_name="删除时间")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="authored_comments", to=settings.AUTH_USER_MODEL, verbose_name="作者")),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="deleted_comments", to=settings.AUTH_USER_MODEL, verbose_name="删除人")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="replies", to="messaging.comment", verbose_name="父评论")),
                ("thread", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comments", to="messaging.commentthread", verbose_name="评论区")),
            ],
            options={
                "verbose_name": "评论",
                "verbose_name_plural": "评论",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("comment", "评论"), ("review", "审核"), ("discipline", "纪律")], max_length=20, verbose_name="类别")),
                ("event", models.CharField(max_length=64, verbose_name="事件")),
                ("payload", models.JSONField(blank=True, default=dict, verbose_name="载荷")),
                ("read_at", models.DateTimeField(blank=True, null=True, verbose_name="已读时间")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL, verbose_name="接收人")),
            ],
            options={
                "verbose_name": "通知",
                "verbose_name_plural": "通知",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="UserMute",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField(blank=True, default="", verbose_name="理由")),
                ("starts_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="开始时间")),
                ("ends_at", models.DateTimeField(blank=True, null=True, verbose_name="结束时间")),
                ("lifted_at", models.DateTimeField(blank=True, null=True, verbose_name="解除时间")),
                ("muted_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="issued_mutes", to=settings.AUTH_USER_MODEL, verbose_name="操作人")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mutes", to=settings.AUTH_USER_MODEL, verbose_name="被禁言用户")),
            ],
            options={
                "verbose_name": "禁言",
                "verbose_name_plural": "禁言",
                "ordering": ["-starts_at"],
                "permissions": [("mute_user", "全站禁言")],
            },
        ),
        migrations.AddIndex(
            model_name="comment",
            index=models.Index(fields=["thread", "parent", "created_at"], name="messaging_c_thread__2648d9_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "-created_at"], name="messaging_n_recipie_0f301b_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "read_at"], name="messaging_n_recipie_736adb_idx"),
        ),
        migrations.AddIndex(
            model_name="usermute",
            index=models.Index(fields=["user", "lifted_at", "ends_at"], name="messaging_u_user_id_c1296f_idx"),
        ),
        migrations.RunPython(backfill_threads, migrations.RunPython.noop),
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
