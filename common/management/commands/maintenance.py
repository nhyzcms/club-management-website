from django.core.management.base import BaseCommand, CommandError

from common.maintenance import (
    REASON_OPS,
    REASON_UPDATE,
    enter_ops,
    flag_path,
    leave_ops,
    read_status,
)


class Command(BaseCommand):
    help = "进入 / 结束全站运维拦截（run/MAINTENANCE；含管理后台）。更新进行中时 off 不会中止更新。"

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=("on", "off", "status"),
            help="on=进入运维拦截，off=结束运维，status=查看当前旗标",
        )
        parser.add_argument(
            "--message",
            default="",
            help="展示在维护页上的说明（仅 on）",
        )

    def handle(self, *args, **options):
        action = options["action"]
        path = flag_path()
        if action == "status":
            status = read_status(path)
            if status is None:
                self.stdout.write("off")
                return
            self.stdout.write(status.reason)
            if status.message:
                self.stdout.write(status.message)
            if status.reason == REASON_UPDATE:
                self.stdout.write(
                    f"{status.step} {status.step_index}/{status.step_total}"
                )
            return
        if action == "on":
            status = enter_ops(path, options["message"])
            if status.reason == REASON_UPDATE:
                self.stdout.write(
                    self.style.WARNING("更新进行中：已记下结束后恢复运维拦截")
                )
            else:
                self.stdout.write(self.style.SUCCESS("已进入运维拦截（全站 503）"))
            return
        if action == "off":
            status = read_status(path)
            if status is None:
                self.stdout.write("已经是关闭状态")
                return
            if status.reason == REASON_UPDATE:
                leave_ops(path)
                self.stdout.write(
                    self.style.WARNING("更新仍在进行：只取消了结束后的运维拦截")
                )
                return
            if status.reason != REASON_OPS:
                raise CommandError(f"unknown maintenance reason: {status.reason}")
            leave_ops(path)
            self.stdout.write(self.style.SUCCESS("已结束运维拦截"))
            return
