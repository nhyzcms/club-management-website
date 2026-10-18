"""向全体用户群发「账号有效期说明」站内私信（一次性运营动作）。

用法（仓库根目录）：

    uv run python manage.py send_validity_broadcast --dry-run
    uv run python manage.py send_validity_broadcast --from admin
    uv run python manage.py send_validity_broadcast --from admin --limit 5

每人一条**个性化**私信：账号当前状态、到期时间、剩余有效期、有效期规则
（文案由 ``accounts.validity_summary.format_dm_message`` 生成，与前端弹窗同一口径）。
同时投递一条「收到新私信」站内通知——未认证用户默认看不到顶栏私信入口，
通知是让他们能点进会话的兜底路径。

安全边界：

- 只发给 ``is_active=True`` 且未注销的账号；跳过发送者本人。
- 幂等：同一会话中若已有发送者在 ``--dedupe-days`` 天内发过同样开头的消息，则跳过该人
  （防手滑重跑刷屏）。
- ``--dry-run`` 只统计、打印预览，不落库。
- 直接建 ``Conversation`` / ``Message``：不走 ``start_private`` 的「对方须已认证」门禁，
  但发送者仍需是真实账号（默认取最早创建的超级管理员）。
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.validity_summary import account_validity, format_dm_message
from accounts.models import profile_of
from messaging.models import Conversation, Message
from messaging.services import notify

MARKER = "【账号有效期说明】"


class Command(BaseCommand):
    help = "向全体用户群发账号有效期说明私信（到期时间 / 剩余有效期 / 规则）。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from", dest="sender", default="",
            help="发送者用户名；默认取最早创建的超级管理员。",
        )
        parser.add_argument("--dry-run", action="store_true", help="只统计与预览，不落库。")
        parser.add_argument("--limit", type=int, default=0, help="最多发送给 N 人（0 = 全部）。")
        parser.add_argument(
            "--dedupe-days", type=int, default=7,
            help="同一会话内该天数内已发过同样消息则跳过（默认 7 天）。",
        )

    def handle(self, *args, **options):
        sender = self._resolve_sender(options["sender"])
        dry = options["dry_run"]
        limit = max(0, options["limit"])
        since = timezone.now() - timedelta(days=max(0, options["dedupe_days"]))

        recipients = (
            User.objects
            .filter(is_active=True, profile__deleted_at__isnull=True)
            .exclude(pk=sender.pk)
            .order_by("pk")
        )
        if limit:
            recipients = recipients[:limit]

        sent = skipped = failed = 0
        previews: list[str] = []
        for user in recipients.iterator():
            validity = account_validity(user)
            content = format_dm_message(user, validity)
            conversation = (
                Conversation.objects
                .filter(participants=sender)
                .filter(participants=user)
                .first()
            )
            if conversation is not None and Message.objects.filter(
                conversation=conversation,
                sender=sender,
                content__startswith=MARKER,
                created_at__gte=since,
            ).exists():
                skipped += 1
                continue
            if dry:
                sent += 1
                if len(previews) < 3:
                    previews.append(f"--- {user.username} ---\n{content}")
                continue
            try:
                with transaction.atomic():
                    if conversation is None:
                        conversation = Conversation.objects.create()
                        conversation.participants.set([sender, user])
                    Message.objects.create(
                        conversation=conversation, sender=sender, content=content,
                    )
                    Conversation.objects.filter(pk=conversation.pk).update(
                        updated_at=timezone.now(),
                    )
                    # 未认证用户顶栏没有私信入口：靠站内通知把人引到会话。
                    notify(
                        user, "dm", "new_message", actor=sender,
                        payload={
                            "type": "dm",
                            "id": conversation.pk,
                            "title": conversation.title or "",
                            "url": f"/messages/{conversation.pk}",
                        },
                    )
                sent += 1
            except Exception as exc:  # noqa: BLE001 - 单人失败不阻断全量群发
                failed += 1
                self.stderr.write(f"发送失败 user={user.pk} {user.username}: {exc}")

        verb = "将发送" if dry else "已发送"
        self.stdout.write(
            f"{verb} {sent} 条，跳过（近期已发）{skipped} 条，失败 {failed} 条；"
            f"发送者 {sender.username}（{sender.pk}）。"
        )
        for preview in previews:
            self.stdout.write(preview)

    def _resolve_sender(self, username: str) -> User:
        if username:
            try:
                sender = User.objects.get(username=username, is_active=True)
            except User.DoesNotExist as exc:
                raise CommandError(f"发送者不存在或已停用：{username}") from exc
        else:
            sender = (
                User.objects.filter(is_superuser=True, is_active=True)
                .order_by("date_joined", "pk")
                .first()
            )
        if sender is None:
            raise CommandError("找不到可用的超级管理员，请用 --from 指定发送者。")
        profile = profile_of(sender)
        if profile is not None and profile.deleted_at is not None:
            raise CommandError("发送者账号已注销。")
        return sender
