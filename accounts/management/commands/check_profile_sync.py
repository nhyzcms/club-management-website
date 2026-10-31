"""校验 ``Profile`` 与 ``AccountIdentity`` / ``AccountLifecycle`` 是否一致。

**为什么需要这个命令**：PR 3 要删掉 ``Profile`` 的 8 个旧列。删之前必须确认新表
完整——任何一处双写遗漏，删列后那部分数据就永久丢了，而且不会报错。

双写（``Profile.save()`` → ``sync_from_profile``）覆盖了所有走 ``save()`` 的写点，
但覆盖不了：

- 迁移回填之后、双写上线之前创建的行（PR 1 → PR 2a 之间的窗口）
- 任何绕过 ``save()`` 的写入（``queryset.update()`` / 裸 SQL / 数据导入）

所以删列前跑一次全量对比，是这个迁移唯一可靠的终点检查。

用法::

    python manage.py check_profile_sync           # 只报告
    python manage.py check_profile_sync --fix     # 报告并修复（以 Profile 为准）

退出码：0 = 全部一致，1 = 有不一致（便于 CI / 部署脚本判定）。
"""
from __future__ import annotations

from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand

from accounts.models import AccountIdentity, AccountLifecycle, Profile
from accounts.sync import sync_from_profile


def _has_field(model, name):
    """PR 3 删掉旧列后，``Profile`` 上就不再有这些字段。

    命令要能自适应：字段还在就对比，不在就跳过（此时退化为「只查新表缺行」）。
    否则 PR 3 一上线这个工具就废了——而它恰恰是之后排查数据问题的第一入口。
    """
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False

# (Profile 字段, 新表字段, 比较方式)
IDENTITY_FIELDS = [
    ("real_name", "real_name", "text"),
    ("identity", "identity", "text"),
    ("card_no", "pending_card_no", "text"),  # 唯一改名的列
]
LIFECYCLE_FIELDS = [
    ("registration_deadline", "registration_deadline", "text"),
    ("expiry_disabled_at", "expiry_disabled_at", "text"),
    ("deleted_at", "deleted_at", "text"),
    ("validity_notice_ack", "validity_notice_ack", "text"),
    ("must_change_password", "must_change_password", "bool"),
]


def _norm(value):
    """空值归一：``None`` 与 ``""`` 视为相同（CharField 的两种空表示）。"""
    if value is None or value == "":
        return ""
    return value


def _same(old, new, kind):
    """按字段类型比较。

    布尔不能走 ``_norm``——``False`` 与 ``None`` 归一后会变成 ``False`` vs ``""``，
    把「未设置」误报成「不一致」。
    """
    if kind == "bool":
        return bool(old) == bool(new)
    return _norm(old) == _norm(new)


class Command(BaseCommand):
    help = "校验 Profile 与 B4 拆出的新表是否一致（PR 3 删旧列前必跑）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix", action="store_true",
            help="以 Profile 为准，把不一致的行同步到新表",
        )

    def handle(self, *args, **options):
        fix = options["fix"]
        profiles = Profile.objects.all().select_related("user")
        identities = {i.user_id: i for i in AccountIdentity.objects.all()}
        lifecycles = {l.user_id: l for l in AccountLifecycle.objects.all()}

        missing_identity = []
        missing_lifecycle = []
        mismatched = []

        for profile in profiles.iterator():
            uid = profile.user_id
            ident = identities.get(uid)
            life = lifecycles.get(uid)

            if ident is None:
                missing_identity.append(uid)
            if life is None:
                missing_lifecycle.append(uid)
            if ident is None or life is None:
                continue

            diffs = []
            for old_f, new_f, kind in IDENTITY_FIELDS:
                if not _has_field(Profile, old_f):
                    continue
                if not _same(getattr(profile, old_f), getattr(ident, new_f), kind):
                    diffs.append(
                        f"identity.{new_f}: Profile={getattr(profile, old_f)!r} "
                        f"新表={getattr(ident, new_f)!r}"
                    )
            for old_f, new_f, kind in LIFECYCLE_FIELDS:
                if not _has_field(Profile, old_f):
                    continue
                if not _same(getattr(profile, old_f), getattr(life, new_f), kind):
                    diffs.append(
                        f"lifecycle.{new_f}: Profile={getattr(profile, old_f)!r} "
                        f"新表={getattr(life, new_f)!r}"
                    )
            if diffs:
                mismatched.append((uid, profile.user.username, diffs))

        total = profiles.count()
        self.stdout.write(f"Profile 共 {total} 行")
        self.stdout.write(f"  新表缺行：identity {len(missing_identity)} / lifecycle {len(missing_lifecycle)}")
        self.stdout.write(f"  字段不一致：{len(mismatched)} 行")

        for uid in missing_identity[:20]:
            self.stdout.write(f"    [缺 identity] user_id={uid}")
        for uid in missing_lifecycle[:20]:
            self.stdout.write(f"    [缺 lifecycle] user_id={uid}")
        for uid, username, diffs in mismatched[:20]:
            self.stdout.write(f"    [不一致] user_id={uid} ({username})")
            for d in diffs:
                self.stdout.write(f"        {d}")

        bad = bool(missing_identity or missing_lifecycle or mismatched)

        if bad and fix:
            if not all(_has_field(Profile, f) for f, _, _ in IDENTITY_FIELDS + LIFECYCLE_FIELDS):
                self.stdout.write(self.style.ERROR(
                    "旧列已删除（PR 3 之后），无法再以 Profile 为准修复——"
                    "此时新表就是唯一真源，缺行请直接排查写入路径"
                ))
                raise SystemExit(1)
            fixed = 0
            for profile in profiles.iterator():
                sync_from_profile(profile)
                fixed += 1
            self.stdout.write(self.style.WARNING(f"已按 Profile 修复 {fixed} 行"))
            return

        if bad:
            self.stdout.write(self.style.ERROR(
                "存在不一致——PR 3 删旧列前必须处理（加 --fix 以 Profile 为准修复）"
            ))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("全部一致，可以进入 PR 3 删旧列"))
