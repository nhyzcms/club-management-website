"""把仓库里既有的静态全景素材（static/panorama/pano_*.jpg）导进 panorama 应用。

用法（仓库根目录）：

    uv run python manage.py import_static_panoramas --dry-run
    uv run python manage.py import_static_panoramas

幂等：以「原文件名 + 来源=静态素材导入」为键跳过已导入的图，可反复执行。
既有的静态页 static/panorama/index.html 与打包脚本**保持不动**——它是新系统的兜底，
待新全景浏览页上线并验证后再单独下线。
"""
from __future__ import annotations

import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from panorama.models import Panorama
from panorama.services import PanoramaImportError, import_panorama

DEFAULT_SOURCE_DIR = "static/panorama"
DEFAULT_TITLE_PREFIX = "校园全景"


def _natural_key(path: Path):
    """pano_2 排在 pano_10 前面（按文件名里的数字段排序）。"""
    return ([int(part) for part in re.findall(r"\d+", path.stem)] or [0], path.name)


class Command(BaseCommand):
    help = "把既有静态全景素材导入 panorama 应用并切片（幂等，可反复执行）。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dir", default=DEFAULT_SOURCE_DIR,
            help=f"素材目录（默认 {DEFAULT_SOURCE_DIR}）",
        )
        parser.add_argument(
            "--title-prefix", default=DEFAULT_TITLE_PREFIX,
            help=f"标题前缀（默认「{DEFAULT_TITLE_PREFIX}」，标题形如「校园全景 3」）",
        )
        parser.add_argument("--order-start", type=int, default=1, help="首张的排序值（默认 1）")
        parser.add_argument("--dry-run", action="store_true", help="只列出将导入的文件，不落库")
        parser.add_argument("--force", action="store_true", help="已导入过的同名素材重切片")

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"])
        if not source_dir.is_dir():
            raise CommandError(f"素材目录不存在：{source_dir}")

        files = sorted(source_dir.glob("pano_*.jpg"), key=_natural_key)
        if not files:
            self.stdout.write(self.style.WARNING(f"{source_dir} 下没有 pano_*.jpg，无需导入"))
            return

        prefix = options["title_prefix"]
        order = options["order_start"]
        imported = skipped = failed = 0

        for path in files:
            title = f"{prefix} {order}"
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] {path.name} → 「{title}」")
                order += 1
                continue

            existing = Panorama.objects.filter(
                source_name=path.name, origin=Panorama.ORIGIN_IMPORT,
            ).first()
            if existing is not None and not options["force"]:
                self.stdout.write(f"跳过（已导入 #{existing.pk}）：{path.name}")
                skipped += 1
                order += 1
                continue
            if existing is not None:
                existing.delete()

            with path.open("rb") as handle:
                try:
                    panorama = import_panorama(
                        upload=File(handle, name=path.name),
                        title=title,
                        description="由仓库既有静态素材导入（static/panorama）。",
                        order=order,
                        origin=Panorama.ORIGIN_IMPORT,
                    )
                except PanoramaImportError as exc:
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"导入失败：{path.name} — {exc}"))
                    order += 1
                    continue

            if panorama.status == Panorama.STATUS_READY:
                imported += 1
                self.stdout.write(self.style.SUCCESS(
                    f"已导入：{path.name} → #{panorama.pk}"
                    f"（{panorama.width}×{panorama.height}，{len(panorama.tile_levels)} 级层次图）"
                ))
            else:
                failed += 1
                self.stderr.write(self.style.ERROR(
                    f"切片失败：{path.name} → #{panorama.pk} — {panorama.error}"
                ))
            order += 1

        self.stdout.write(f"完成：导入 {imported}，跳过 {skipped}，失败 {failed}。")
