"""明信片照片生命周期周期兜底（方案 §7「照片留存」）。

惰性触发（请求过 _phase_guard 时活动结束即清）之外的兜底，建议 cron 每小时：

    20 * * * * cd /opt/club && set -a && . ./.env && set +a && \
        .venv/bin/python manage.py postcard_photo_gc >> backups/postcard_gc.log 2>&1

做三件事（幂等，重复跑无副作用）：
1. 已结束活动 → 照片文件全量清除（登记数据保留）；
2. 终态失败照片（ai_failed / manual_failed）超 24h → 删文件；
3. pending 卡死超 1h（后台线程被杀 / 进程重启）→ 转人工复核。
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from events.modules.postcard import lifecycle


class Command(BaseCommand):
    help = "明信片照片生命周期兜底：活动结束全清 / 失败照片 24h TTL / 卡死 pending 转人工"

    def handle(self, *args, **options):
        stats = lifecycle.gc_sweep()
        self.stdout.write(json.dumps(stats, ensure_ascii=False))
