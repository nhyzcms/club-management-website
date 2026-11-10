"""nginx 生效配置与站点策略的漂移自检（审计 #272 / #275）。

**为什么需要这个命令**：`client_max_body_size` 有三处「真源」——站点策略表、
仓库里的 `scripts/install.sh` 模板、以及线上 `/etc/nginx/conf.d/*.conf`。前两者
跟着代码走，第三者是部署时的产物，**不会随应用部署更新**。结果就是仓库里写着
600M、测试断言「不许是 20M」，而线上仍然是 20M（2026-11-04 实测：19MB 成功、
21MB 直接 413）。测试只能证明仓库文件正确，证明不了线上生效值。

同理 `/media/` 由 nginx 直出，location 级 `add_header` 会**覆盖** server 级继承
——加安全头的同时必须把 HSTS 等重复声明一遍，否则顺手丢头。

约定：**站点策略是上限的唯一来源，nginx 只做 ≥ 策略的兜底**。本命令按这个方向
判漂移（nginx < 策略 = 错；nginx 明显过大 = 提个醒）。
"""
import json
import re
import subprocess

from django.core.management.base import BaseCommand, CommandError

from common.policy import get_policy

#: 严格大于策略值即合规；超出这么多倍提醒「兜底过宽」（可能是历史遗留 600M）。
_OVERSHOOT_WARN_FACTOR = 4

#: `/media/` 必须带的三个头（`always` 保证 4xx/5xx 也带上）。
_MEDIA_REQUIRED_HEADERS = (
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Content-Security-Policy",
)

_UNIT = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([kKmMgG]?)$")
_BODY_SIZE_RE = re.compile(r"\bclient_max_body_size\s+([^;]+);")
_COMMENT_RE = re.compile(r"#[^\n]*")


def parse_size(text: str) -> int | None:
    """把 nginx 的尺寸写法（``600M`` / ``20m`` / ``1024`` / ``1G``）换成字节。"""
    match = _SIZE_RE.match((text or "").strip())
    if not match:
        return None
    number, unit = match.groups()
    return int(float(number) * _UNIT[unit.lower()])


def body_size_directives(config_text: str) -> list[int]:
    """配置文本里所有 ``client_max_body_size`` 的字节值（解析不了的不计）。"""
    values = []
    for raw in _BODY_SIZE_RE.findall(_COMMENT_RE.sub("", config_text)):
        size = parse_size(raw)
        if size is not None:
            values.append(size)
    return values


def iter_blocks(config_text: str, opener: str):
    """粗粒度提取 ``opener { ... }`` 的块体（按花括号配平）。

    只看配置文本，不建 nginx 语法树——够用且不会因为一行未知指令就崩。
    """
    for start in re.finditer(re.escape(opener) + r"\s*\{", config_text):
        depth = 0
        index = start.end() - 1
        for offset in range(index, len(config_text)):
            char = config_text[offset]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield config_text[index : offset + 1]
                    break


def missing_media_headers(config_text: str) -> list[str]:
    """``/media/`` location 里缺哪些安全头（没有该 location 时返回空——那是另一回事）。"""
    blocks = list(iter_blocks(config_text, "location /media/"))
    if not blocks:
        return []
    body = "\n".join(blocks)
    return [
        header
        for header in _MEDIA_REQUIRED_HEADERS
        if not re.search(rf"add_header\s+{re.escape(header)}\b", body)
    ]


def load_nginx_config(path: str | None) -> str:
    """读配置：给定文件就读文件，否则跑 ``nginx -T``（需 root 或免密 sudo）。"""
    if path:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError as exc:
            raise CommandError(f"读不到 {path}：{exc}") from exc

    for command in (["nginx", "-T"], ["sudo", "-n", "nginx", "-T"]):
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=20, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return result.stdout
    raise CommandError(
        "拿不到 nginx 生效配置。请在服务器上以有权限的身份运行，"
        "或用 --nginx-conf 指向配置文件。"
    )


class Command(BaseCommand):
    help = "自检 nginx 的 client_max_body_size 与 /media/ 安全头是否和站点策略一致"

    def add_arguments(self, parser):
        parser.add_argument(
            "--nginx-conf", default=None,
            help="要检查的配置文件路径；省略则运行 nginx -T 取生效配置",
        )
        parser.add_argument(
            "--required-bytes", type=int, default=None,
            help="覆盖「nginx 必须 ≥ 多少字节」的默认判断（默认取站点策略）",
        )
        parser.add_argument("--json", action="store_true", help="机器可读输出")

    def handle(self, *args, **options):
        if options["required_bytes"]:
            required = options["required_bytes"]
            source = "--required-bytes"
        else:
            policy = get_policy()
            # tus 媒体上传同样过 nginx：兜底值必须覆盖两者中更大的那个。
            required = max(policy.sync_upload_max_bytes, policy.tus_media_max_bytes)
            source = (
                "tus_media_max_bytes"
                if policy.tus_media_max_bytes >= policy.sync_upload_max_bytes
                else "sync_upload_max_bytes"
            )

        config = load_nginx_config(options["nginx_conf"])
        sizes = body_size_directives(config)
        missing = missing_media_headers(config)

        problems: list[str] = []
        warnings: list[str] = []
        if not sizes:
            problems.append(
                "配置里没有 client_max_body_size —— nginx 默认 1M，"
                "任何附件上传都会 413。"
            )
        else:
            smallest = min(sizes)
            if smallest < required:
                problems.append(
                    f"client_max_body_size 最小 {smallest} 字节（{_human(smallest)}）"
                    f" < 站点策略 {required} 字节（{_human(required)}，来自 {source}）"
                    f" —— {_human(required)} 以下的文件会在 nginx 层被 413，Django 收不到。"
                )
            elif smallest > required * _OVERSHOOT_WARN_FACTOR:
                # 只提醒不判错：600M 兜底 + 50M 策略是刻意留的余量（tus 媒体上传
                # 也要走 nginx），不该因此让部署脚本失败。
                warnings.append(
                    f"client_max_body_size 最小 {_human(smallest)} 远超策略 {_human(required)}"
                    f"（>{_OVERSHOOT_WARN_FACTOR}×）——不算错，但 nginx 的兜底范围过宽，"
                    "站点策略挡不住的部分会先落到 Django。"
                )
        if missing:
            problems.append(
                "/media/ 的 location 缺安全头：" + "、".join(missing)
                + "（直出的上传文件因此可被嗅探类型 / 被第三方页面内嵌）"
            )

        payload = {
            "ok": not problems,
            "required_bytes": required,
            "required_source": source,
            "client_max_body_sizes": sizes,
            "missing_media_headers": missing,
            "problems": problems,
            "warnings": warnings,
        }

        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"提醒：{warning}"))

        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        elif problems:
            self.stdout.write(self.style.ERROR("nginx 与站点策略不一致："))
            for problem in problems:
                self.stdout.write(f"  - {problem}")
            self.stdout.write(
                "\n修法：以 scripts/install.sh 的 nginx 模板为准同步线上配置，"
                "然后 nginx -t && systemctl reload nginx。"
            )
        else:
            self.stdout.write(self.style.SUCCESS(
                f"nginx 配置与站点策略一致：client_max_body_size "
                f"{_human(min(sizes))} ≥ {_human(required)}，/media/ 安全头齐全。"
            ))

        if problems:
            raise CommandError("检测到 nginx 配置漂移（见上）。")


def _human(size: int) -> str:
    for unit, scale in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= scale:
            return f"{size / scale:.0f}{unit}"
    return f"{size}B"
