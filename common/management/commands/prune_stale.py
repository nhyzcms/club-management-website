"""清理过期数据（B9）。

## 删什么

每一条都有明确的「过了就没用」语义：

| 表 | 保留 | 为什么 |
|---|---|---|
| `LoginChallenge` | 过期 7 天 | 登录挑战是一次性令牌，过期即废 |
| `StepUpEmailCode` | 过期 1 天 | 验证码同理，留一天够排查 |
| `LoginEvent` | 180 天 | 登录审计，半年足够追查异常 |
| `Notification` | 已读且 90 天 | 未读的**不删**（见下） |
| `NotificationDelivery` | 已送达且 30 天 | 投递记录，送达后无重试价值 |

## 不删什么

**`Notification` 未读的一律不碰。** 删掉用户没看过的通知就是丢消息——那是功能
缺陷，不是清理。

**`AuthCode` 不碰。** 码可能长期有效，且 `AuthCodeRedemption` 挂着它的兑换记录。
删码会 CASCADE 掉兑换记录，那是审计数据，不该被「清理过期」顺手带走。

## 为什么默认 dry-run

生产库上删错了没法恢复。先跑一次看数量，确认后再加 `--apply`。

`--apply` 时会打印每张表实际删掉的行数（含 CASCADE 带走的），不是预估数。
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import LoginChallenge, LoginEvent, StepUpEmailCode
from messaging.models import Notification, NotificationDelivery


class Command(BaseCommand):
    help = "清理过期的一次性凭据、审计日志、已读通知（默认只统计，加 --apply 才删）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="真正执行删除；不加时只打印待删数量",
        )
        parser.add_argument(
            "--challenge-days", type=int, default=7,
            help="登录挑战过期后再保留几天（默认 7）",
        )
        parser.add_argument(
            "--stepup-days", type=int, default=1,
            help="安全验证码过期后再保留几天（默认 1）",
        )
        parser.add_argument(
            "--login-event-days", type=int, default=180,
            help="登录审计保留天数（默认 180）",
        )
        parser.add_argument(
            "--notification-days", type=int, default=90,
            help="已读通知保留天数（默认 90）",
        )
        parser.add_argument(
            "--delivery-days", type=int, default=30,
            help="已送达投递记录保留天数（默认 30）",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        apply = options["apply"]

        plan = [
            (
                "登录挑战（过期 %d 天）" % options["challenge_days"],
                LoginChallenge.objects.filter(
                    expires_at__lt=now - timedelta(days=options["challenge_days"])
                ),
            ),
            (
                "安全验证码（过期 %d 天）" % options["stepup_days"],
                StepUpEmailCode.objects.filter(
                    expires_at__lt=now - timedelta(days=options["stepup_days"])
                ),
            ),
            (
                "登录审计（%d 天前）" % options["login_event_days"],
                LoginEvent.objects.filter(
                    created_at__lt=now - timedelta(days=options["login_event_days"])
                ),
            ),
            (
                "已读通知（%d 天前）" % options["notification_days"],
                Notification.objects.filter(
                    read_at__isnull=False,
                    created_at__lt=now - timedelta(days=options["notification_days"]),
                ),
            ),
            (
                "已送达投递（%d 天前）" % options["delivery_days"],
                NotificationDelivery.objects.filter(
                    status=NotificationDelivery.STATUS_SENT,
                    sent_at__lt=now - timedelta(days=options["delivery_days"]),
                ),
            ),
        ]

        mode = "执行" if apply else "预演（加 --apply 才真正删除）"
        self.stdout.write(f"模式：{mode}\n")

        grand_total = 0
        for label, queryset in plan:
            if apply:
                deleted, _per_model = queryset.delete()
                grand_total += deleted
                self.stdout.write(f"  {label}：删除 {deleted} 行")
            else:
                count = queryset.count()
                grand_total += count
                self.stdout.write(f"  {label}：待删 {count} 行")

        verb = "删除" if apply else "待删"
        self.stdout.write(f"\n合计{verb} {grand_total} 行")

        if apply and grand_total:
            self.stdout.write(
                "\n注意：行数含 CASCADE 带走的从属记录。例如删一条已读通知时，"
                "它的 NotificationDelivery 会一起消失——所以后面的「已送达投递」"
                "可能显示 0 行，那不是没删，是已经跟着上一项删掉了。"
            )

        if not apply and grand_total:
            self.stdout.write(
                self.style.WARNING(
                    "\n以上为预演。确认数量无误后加 --apply 执行。"
                )
            )
        elif not grand_total:
            self.stdout.write(self.style.SUCCESS("\n没有需要清理的数据。"))
