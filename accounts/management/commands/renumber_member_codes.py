"""按当前识别码规则整批重算社员识别码（末位避开 0/2/4，见 member_codes.py）。

用法（仓库根目录）：

    uv run python manage.py renumber_member_codes               # 只预览，不写库
    uv run python manage.py renumber_member_codes --apply       # 真正写库
    uv run python manage.py renumber_member_codes --cohort 3    # 只处理某一届

**默认 dry-run**：重算会让已打印工牌 / 已导出二维码条形码与系统不一致，必须人工确认后
再加 ``--apply``。规则本身是「按原序号从小到大重新分配」（保持姓名顺序），绑定关系、
状态、批次等字段一律不动，只改 ``code``。

写库采用两步法：先把待改行置成 ``TMP<id>`` 临时码，再写最终码——否则「A 的新码正好
是 B 的旧码」会撞 ``code`` 的唯一约束。
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.member_codes import (
    MemberCodeError,
    generate_code,
    is_preferred_code,
    next_serial,
)
from accounts.models import MemberIdentity


def _sort_key(identity: MemberIdentity):
    """组内按原识别码序号升序（= 原分配顺序）；非 8 位数字的历史码排最后。"""
    code = (identity.code or "").strip()
    if len(code) == 8 and code.isdigit():
        return (0, int(code))
    return (1, code)


def plan_renumber(*, cohort: int | None = None):
    """返回 [(identity, 旧码, 新码)]，只含真正变化的行。"""
    qs = MemberIdentity.objects.all()
    if cohort is not None:
        qs = qs.filter(cohort=cohort)

    groups: dict[tuple[int, int], list[MemberIdentity]] = defaultdict(list)
    for identity in qs:
        groups[(identity.admit_year, identity.cohort)].append(identity)

    changes = []
    for (admit_year, group_cohort), rows in sorted(groups.items()):
        rows.sort(key=_sort_key)
        taken: set[str] = set()
        for identity in rows:
            serial = next_serial(admit_year, group_cohort, taken)
            new_code = generate_code(admit_year, group_cohort, serial)
            taken.add(new_code)
            if new_code != identity.code:
                changes.append((identity, identity.code, new_code))
    return changes


class Command(BaseCommand):
    help = "按当前规则整批重算社员识别码（默认只预览；--apply 才写库）"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="真正写库（默认只预览）")
        parser.add_argument("--cohort", type=int, default=None, help="只处理该届（届数）")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        cohort = options["cohort"]

        try:
            changes = plan_renumber(cohort=cohort)
        except MemberCodeError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        total = MemberIdentity.objects.count()
        if cohort is not None:
            total = MemberIdentity.objects.filter(cohort=cohort).count()

        for identity, old_code, new_code in changes:
            self.stdout.write(
                f"{identity.name}（{identity.cohort}届）: {old_code} → {new_code}"
            )

        unchanged = total - len(changes)
        if not changes:
            self.stdout.write(self.style.SUCCESS("全部识别码已符合规则，无需重算。"))
            return

        self.stdout.write(
            f"\n待变更 {len(changes)} 条 · 不变 {unchanged} 条（共 {total} 条）"
        )
        unlucky_before = sum(1 for _, old, _ in changes if not is_preferred_code(old))
        self.stdout.write(f"其中旧码校验码含 2/4 或末位为 0 的 {unlucky_before} 条")

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "预览模式，未写库。确认后加 --apply 执行；"
                "重算后请重新导出二维码 / 条形码，已打印工牌需换发。"
            ))
            return

        with transaction.atomic():
            # 第一步：临时码，避开「新码 = 另一行旧码」的唯一约束冲突。
            for identity, _old, _new in changes:
                identity.code = f"TMP{identity.pk}"
                identity.save(update_fields=["code"])
            # 第二步：写最终码。
            for identity, _old, new_code in changes:
                identity.code = new_code
                identity.save(update_fields=["code"])

        self.stdout.write(self.style.SUCCESS(f"已重算 {len(changes)} 条识别码。"))
        self.stdout.write("后续：重新导出二维码 / 条形码；已打印工牌需按新码换发。")
