"""清理问卷文件题上传的孤儿附件（审计 #271）。

## 为什么需要它

``survey_upload`` 是匿名可写的上传端点。加了台账（``SurveyUpload``）之后，
「谁传的、多大、什么时候」有据可查，但文件本身不会自己消失：填了一半放弃的
问卷、上传后没提交的答案，都会在 ``MEDIA_ROOT/survey_uploads/`` 留下来。
没有回收任务，磁盘只增不减（对比 tus 的 ``sweep_stale_tus_uploads``）。

## 判据

**是否被某条问卷作答引用**——不是「有没有台账」。台账只证明「这个文件曾被
上传」，不证明「有人用它」。引用的判定做法是把所有作答的 JSON 摊平成一段
文本，再检查文件路径是否出现：SurveyJS 的文件题会把上传返回的 URL 原样存进
answers，所以路径（``survey_uploads/<hex>.png``）一定在字符串里。

问卷作答是三位数量级、每条几 KB，全量扫一遍比逐文件查库便宜得多。

## 为什么默认 dry-run

生产库 + 磁盘上的文件，删错了都没法从数据库恢复。先跑一次看数量，确认后
再加 ``--apply``。

## 不会碰的东西

- 未超过 ``--days`` 的新文件（默认 7 天）：问卷可能在几天后才提交。
- 有任何作答引用的文件，哪怕很老——那是在用的数据。
"""
from datetime import timedelta

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone

from activities.models import QuestionnaireResponse, SurveyUpload


def _iter_strings(value):
    """递归摊平 JSON 里的所有字符串值（dict / list / 标量都覆盖）。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def referenced_blob() -> str:
    """把所有问卷作答里的字符串拼成一段文本，供 ``path in blob`` 判定。"""
    parts = []
    for answers in QuestionnaireResponse.objects.values_list("answers", flat=True).iterator():
        parts.extend(_iter_strings(answers))
    return "\n".join(parts)


class Command(BaseCommand):
    help = "清理未被任何问卷作答引用的问卷附件（默认只统计，加 --apply 才删）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="真正执行删除；不加时只打印待删数量",
        )
        parser.add_argument(
            "--days", type=int, default=7,
            help="只清上传超过 N 天的文件（默认 7，给「上传后过几天才提交」留窗口）",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        apply = options["apply"]

        candidates = list(
            SurveyUpload.objects.filter(created_at__lt=cutoff).order_by("created_at")
        )
        blob = referenced_blob()
        orphans = [row for row in candidates if row.path not in blob]
        bytes_total = sum(row.size for row in orphans)

        mode = "执行" if apply else "预演（加 --apply 才真正删除）"
        self.stdout.write(f"模式：{mode}")
        self.stdout.write(f"超过 {options['days']} 天的台账：{len(candidates)} 行")
        self.stdout.write(f"其中未被作答引用：{len(orphans)} 个，共 {bytes_total} 字节\n")

        if not orphans:
            self.stdout.write(self.style.SUCCESS("没有需要清理的文件。"))
            return

        if not apply:
            for row in orphans[:20]:
                self.stdout.write(f"  {row.created_at:%Y-%m-%d %H:%M}  {row.size:>10}  {row.path}")
            if len(orphans) > 20:
                self.stdout.write(f"  …还有 {len(orphans) - 20} 个")
            self.stdout.write(
                self.style.WARNING("\n以上为预演。确认数量无误后加 --apply 执行。")
            )
            return

        deleted_files = 0
        deleted_rows = 0
        for row in orphans:
            # 文件可能已被手工删掉：delete() 对不存在的路径是静默的，
            # 台账行照删——留着只会让配额统计虚高。
            default_storage.delete(row.path)
            deleted_files += 1
            row.delete()
            deleted_rows += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"删除文件 {deleted_files} 个、台账 {deleted_rows} 行，共 {bytes_total} 字节。"
            )
        )
