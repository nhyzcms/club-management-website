"""定时兜底执行账号身份有效期（ADR-0041）+ 到期前的站内提醒。

用法（仓库根目录）：

    uv run python manage.py enforce_validity
    uv run python manage.py enforce_validity --dry-run
    uv run python manage.py enforce_validity --skip-notices

惰性执行已覆盖登录 / 请求时；本命令供 cron / systemd timer 定时兜底：遍历全部活跃用户
执行 enforce_account_validity，处理掉长时间在线的过期会话；随后发「身份还剩两个月 /
一个月」的站内提醒（``accounts.validity_notices``，台账保证只发一次）。
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from accounts.validity import enforce_account_validity
from accounts.validity_notices import send_expiry_notices


class Command(BaseCommand):
    help = "执行账号身份有效期规则：撤销过期管理员、停用超期未认证账号；并发到期前提醒。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只统计，不改动")
        parser.add_argument(
            "--skip-notices", action="store_true", help="只执行到期处理，不发到期前提醒",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        admin_expired = unverified_expired = 0
        for user in User.objects.filter(is_active=True).iterator():
            action = enforce_account_validity(user, dry_run=dry)
            if action == "admin_expired":
                admin_expired += 1
            elif action == "unverified_expired":
                unverified_expired += 1

        parts = [f"撤销过期管理员 {admin_expired}，停用超期未认证账号 {unverified_expired}。"]
        if not options["skip_notices"]:
            counts = send_expiry_notices(dry_run=dry)
            parts.append(
                "到期提醒（还剩两个月 "
                f"{counts['expiring_2m']} / 还剩一个月 {counts['expiring_1m']}）。"
            )
        message = "".join(parts)

        if dry:
            self.stdout.write(f"[dry-run] 将{message}")
        else:
            self.stdout.write(self.style.SUCCESS(f"完成：{message}"))
