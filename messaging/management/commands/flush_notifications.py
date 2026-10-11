"""手动排空通知投递队列（异步投递的运维入口，ADR-0024）。

用法（仓库根目录）：

    uv run python manage.py flush_notifications
    uv run python manage.py flush_notifications --limit 500

处理当前进程内存队列与数据库中「已到期 pending」的投递行——用于：观察卡住的
重试、发布窗口后手动补投、排障时确认投递链路。发送按各通道自身语义执行
（email 会复用本进程的共享 SMTP 连接）。
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from messaging.notifications import queue as delivery_queue


class Command(BaseCommand):
    help = "手动排空通知投递：先处理内存队列，再兜底扫描数据库中到期的待投递行。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=200, help="本次最多处理条数（默认 200）",
        )

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        processed = delivery_queue.drain_now(limit=limit)
        self.stdout.write(self.style.SUCCESS(f"完成：处理 {processed} 条投递。"))
