"""打印当前运行版本的快照。

线上排查第一句总是「现在跑的是哪个版本」，让它一条命令就能答，
不必先 SSH 上去看 ``deploy.sh status`` 或翻镜像 tag。
"""
import json

from django.core.management.base import BaseCommand

from common.version import build_info


class Command(BaseCommand):
    help = "打印当前版本快照（镜像内来自 CI 写入的 build_info.json）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="输出 JSON，便于脚本消费",
        )

    def handle(self, *args, **options):
        info = build_info()

        if options["json"]:
            self.stdout.write(json.dumps(info, ensure_ascii=False, indent=2))
            return

        self.stdout.write(f"版本    {info['version']}")
        self.stdout.write(f"基线    {info['base_version']}")
        self.stdout.write(f"渠道    {info['channel']}")
        if info["commit_short"]:
            self.stdout.write(f"提交    {info['commit_short']} ({info['commit']})")
        if info["commits_since_tag"] is not None:
            self.stdout.write(f"距标签  {info['commits_since_tag']} 个提交（{info['tag'] or '无标签'}）")
        if info["built_at"]:
            self.stdout.write(f"构建于  {info['built_at']}  by {info['built_by'] or '未知'}")
        self.stdout.write(f"来源    {info['source']}")
