"""彻底删除账号（物理删除，ADR-0052）——服务器侧应急通道。

用法（仓库根目录）：

    uv run python manage.py hard_delete_account <用户名或id> [--mode keep|purge] \\
        --reason "冒用他人身份注册" --yes

后台 /admin/ 的 User 列表里也有同名动作（同一套业务逻辑
``accounts.hard_delete.hard_delete_account``），日常请优先用后台，方便留痕。

安全边界：

* ``--yes`` 必填：没有它只做预检并打印将被处理的对象，不落库；
* 拒绝删除自己（命令行没有「自己」这个概念，所以只保护最后一个超级管理员）；
* 两种内容模式：``keep``（默认，内容改挂「该用户已注销」墓碑）/ ``purge``（连内容一起删）；
* 每次执行写一条 ``AccountDeletionLog``（actor 记为 ``cli``）。
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from accounts.hard_delete import (
    MODE_CHOICES,
    MODE_KEEP,
    HardDeleteError,
    hard_delete_account,
)

MODE_VALUES = [value for value, _label in MODE_CHOICES]


class Command(BaseCommand):
    help = "彻底删除账号（物理删除，不可恢复）。"

    def add_arguments(self, parser):
        parser.add_argument("identifier", nargs="+", help="用户名或数字 id，可多个")
        parser.add_argument(
            "--mode", choices=MODE_VALUES, default=MODE_KEEP,
            help="内容处理：keep=保留内容并匿名化（默认），purge=连内容一起删",
        )
        parser.add_argument("--reason", default="", help="删除原因（写进审计记录）")
        parser.add_argument(
            "--yes", action="store_true",
            help="确认执行；不加只预检打印，不删除任何东西",
        )

    def handle(self, *args, **options):
        mode = options["mode"]
        reason = options["reason"]
        confirmed = options["yes"]

        targets: list[User] = []
        for raw in options["identifier"]:
            user = None
            if raw.isdigit():
                user = User.objects.filter(pk=int(raw)).first()
            if user is None:
                user = User.objects.filter(username=raw).first()
            if user is None:
                raise CommandError(f"账号不存在：{raw}")
            targets.append(user)

        if not confirmed:
            self.stdout.write(self.style.WARNING("预检模式（未加 --yes，不会删除）："))
            for user in targets:
                self.stdout.write(
                    f"  - {user.username}（#{user.pk}）"
                    f"{' 超级管理员' if user.is_superuser else ' 管理员' if user.is_staff else ''}"
                )
            self.stdout.write(f"内容模式：{mode}")
            self.stdout.write("确认无误后加 --yes 重新执行。")
            return

        failed = 0
        for user in targets:
            try:
                result = hard_delete_account(
                    user, actor=None, mode=mode, reason=reason, ip=None,
                )
            except HardDeleteError as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(
                    f"{user.username}（#{user.pk}）未删除：{exc.message}",
                ))
                continue
            detail = "，".join(
                f"{key}={count}" for key, count in sorted(result.reassigned.items())
            )
            self.stdout.write(self.style.SUCCESS(
                f"已删除 {result.target_username}（#{result.target_id}）"
                f" mode={result.mode} 文件 {result.deleted_files} 个"
                + (f" 改挂：{detail}" if detail else "")
                + (f" 墓碑 #{result.tombstone_id}" if result.tombstone_id else ""),
            ))

        if failed:
            raise CommandError(f"{failed} 个账号未删除。")
