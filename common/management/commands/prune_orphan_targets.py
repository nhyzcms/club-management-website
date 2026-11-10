"""清理孤儿 `ContentTarget`（宿主已删但 target 还在）。

## 为什么会有孤儿

正常删除走 `_on_host_deleted`（`common/targets.py` 里挂的 `post_delete`），
删宿主 → 删 target → CASCADE 带走附件/审核/举报/评论区。

但有三条路径绕过了它：

1. **裸 SQL 删除**（`DELETE FROM news_news WHERE ...`）——不触发 Django 信号。
2. **数据库层 CASCADE**——比如删 `Activity` 时 DB 自己删了 `Submission`，
   但 `Submission` 的 `post_delete` 在 Django 这一侧不会为每条子行都跑一遍。
3. **迁移里删数据**——`RunPython` 直接用 queryset，信号行为取决于用的是历史模型还是真实模型。

孤儿本身不致命（`object_id` 指向不存在的行，读不到东西），但会：
- 让 `ContentTarget` 表无谓增长；
- 让「这条内容有几个附件」这类聚合统计多算。

## 默认 dry-run

和 `prune_stale` 一样。孤儿判定要逐 kind 查一次宿主表，生产上跑一次几十毫秒，
但删错了没法恢复——先看数量。
"""
from django.core.management.base import BaseCommand

from common.models import ContentTarget
from common.targets import KIND_TO_MODEL


class Command(BaseCommand):
    help = "清理宿主已不存在的 ContentTarget 行（默认只统计，加 --apply 才删）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="真正执行删除；不加时只打印待删数量",
        )
        parser.add_argument(
            "--kind", default=None,
            help="只处理某一种 kind（默认全部）",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        only_kind = options["kind"]

        kinds = [only_kind] if only_kind else list(KIND_TO_MODEL)
        unknown = [k for k in kinds if k not in KIND_TO_MODEL]
        if unknown:
            self.stderr.write(f"未知 kind：{unknown}")
            return

        mode = "执行" if apply else "预演（加 --apply 才真正删除）"
        self.stdout.write(f"模式：{mode}\n")

        grand_total = 0
        for kind in kinds:
            from common.targets import model_for

            model = model_for(kind)
            # 该 kind 下所有 target 的 object_id
            target_ids = list(
                ContentTarget.objects.filter(kind=kind).values_list("id", "object_id")
            )
            if not target_ids:
                continue
            # 该 kind 下真实存在的宿主 pk
            live_ids = set(
                model.objects.filter(
                    pk__in=[object_id for _tid, object_id in target_ids]
                ).values_list("pk", flat=True)
            )
            orphans = [tid for tid, object_id in target_ids if object_id not in live_ids]
            if not orphans:
                continue

            if apply:
                deleted, _per_model = ContentTarget.objects.filter(
                    pk__in=orphans,
                ).delete()
                grand_total += deleted
                self.stdout.write(f"  {kind}：删除 {deleted} 行（含 CASCADE 带走的）")
            else:
                grand_total += len(orphans)
                self.stdout.write(f"  {kind}：待删 {len(orphans)} 行")

        verb = "删除" if apply else "待删"
        self.stdout.write(f"\n合计{verb} {grand_total} 行")

        if apply and grand_total:
            self.stdout.write(
                "\n注意：行数含 CASCADE 带走的从属记录——删一个 target 会连带删掉"
                "挂在它上面的附件、审核行、举报案、评论区及其评论。"
            )
        elif not grand_total:
            self.stdout.write(self.style.SUCCESS("\n没有孤儿 target。"))
