"""File-flag maintenance intercept (no database).

``run/MAINTENANCE`` is the source of truth. The updater writes progress JSON
during apply; ops uses ``manage.py maintenance on|off``. Middleware only
reads this file — never SiteSettings — so migrate cannot deadlock SQLite.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from django.conf import settings

REASON_UPDATE = "update"
REASON_OPS = "ops"

# Ordered apply steps shown on the maintenance page (index is 1-based).
# ``rollback`` is an extra label, not part of the happy-path total.
UPDATE_STEPS: tuple[tuple[str, str], ...] = (
    ("drain", "正在拦截访问"),
    ("backup", "正在备份数据库"),
    ("unpack", "正在解包更新"),
    ("sync", "正在替换文件"),
    ("deps", "正在同步依赖"),
    ("migrate", "正在迁移数据库"),
    ("collectstatic", "正在收集静态文件"),
    ("reload", "正在重载服务"),
)
ROLLBACK_STEP = "rollback"
ROLLBACK_LABEL = "正在回滚到上一版本"

UPDATE_STEP_KEYS = tuple(k for k, _ in UPDATE_STEPS)
UPDATE_STEP_LABELS: dict[str, str] = dict(UPDATE_STEPS)
UPDATE_STEP_LABELS[ROLLBACK_STEP] = ROLLBACK_LABEL


def flag_path() -> Path:
    return Path(settings.BASE_DIR) / "run" / "MAINTENANCE"


@dataclass(frozen=True)
class MaintenanceStatus:
    reason: str = REASON_OPS
    message: str = ""
    step: str = ""
    step_index: int = 0
    step_total: int = 0
    sha: str = ""
    resume_ops: bool = False
    ops_message: str = ""

    @property
    def percent(self) -> int:
        if self.step_total <= 0:
            return 0
        return min(100, max(0, int(100 * self.step_index / self.step_total)))

    @property
    def heading(self) -> str:
        if self.reason == REASON_UPDATE:
            return "系统更新中"
        return "系统维护中"

    @property
    def detail(self) -> str:
        if self.message:
            return self.message
        if self.reason == REASON_UPDATE:
            return "网站正在更新，请稍后再访问。"
        return "网站正在维护，请稍后再访问。"


def read_status(flag: Path | None = None) -> MaintenanceStatus | None:
    path = flag if flag is not None else flag_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return MaintenanceStatus()
    if not raw:
        return MaintenanceStatus()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return MaintenanceStatus(message=raw[:200])
    if not isinstance(data, dict):
        return MaintenanceStatus()
    reason = data.get("reason") or REASON_OPS
    if reason not in (REASON_UPDATE, REASON_OPS):
        reason = REASON_OPS
    return MaintenanceStatus(
        reason=reason,
        message=str(data.get("message") or ""),
        step=str(data.get("step") or ""),
        step_index=int(data.get("step_index") or 0),
        step_total=int(data.get("step_total") or 0),
        sha=str(data.get("sha") or ""),
        resume_ops=bool(data.get("resume_ops")),
        ops_message=str(data.get("ops_message") or ""),
    )


def write_status(flag: Path, status: MaintenanceStatus) -> None:
    flag.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(status), ensure_ascii=False, indent=0)
    tmp = flag.with_name(flag.name + ".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(flag)


def enter_ops(flag: Path, message: str = "") -> MaintenanceStatus:
    """Ops maintenance. If an update is running, remember to restore ops after."""
    current = read_status(flag)
    text = (message or "").strip()
    if current is not None and current.reason == REASON_UPDATE:
        status = MaintenanceStatus(
            reason=REASON_UPDATE,
            message=current.message,
            step=current.step,
            step_index=current.step_index,
            step_total=current.step_total,
            sha=current.sha,
            resume_ops=True,
            ops_message=text or current.ops_message,
        )
        write_status(flag, status)
        return status
    status = MaintenanceStatus(reason=REASON_OPS, message=text)
    write_status(flag, status)
    return status


def leave_ops(flag: Path) -> None:
    """Drop ops intercept. Does not abort an in-flight update."""
    current = read_status(flag)
    if current is None:
        return
    if current.reason == REASON_UPDATE:
        write_status(
            flag,
            MaintenanceStatus(
                reason=REASON_UPDATE,
                message=current.message,
                step=current.step,
                step_index=current.step_index,
                step_total=current.step_total,
                sha=current.sha,
                resume_ops=False,
                ops_message="",
            ),
        )
        return
    flag.unlink(missing_ok=True)


def enter_update(flag: Path, *, sha: str = "") -> MaintenanceStatus:
    current = read_status(flag)
    resume_ops = current is not None and (
        current.reason == REASON_OPS or current.resume_ops
    )
    ops_message = ""
    if current is not None:
        if current.reason == REASON_OPS:
            ops_message = current.message
        else:
            ops_message = current.ops_message
    status = MaintenanceStatus(
        reason=REASON_UPDATE,
        message=UPDATE_STEP_LABELS["drain"],
        step="drain",
        step_index=1,
        step_total=len(UPDATE_STEPS),
        sha=sha,
        resume_ops=resume_ops,
        ops_message=ops_message,
    )
    write_status(flag, status)
    return status


def update_progress(flag: Path, step: str, *, sha: str | None = None) -> MaintenanceStatus:
    current = read_status(flag)
    if step == ROLLBACK_STEP:
        index = current.step_index if current else len(UPDATE_STEPS)
        total = current.step_total if current else len(UPDATE_STEPS)
    elif step not in UPDATE_STEP_KEYS:
        raise ValueError(f"unknown maintenance step: {step}")
    else:
        index = UPDATE_STEP_KEYS.index(step) + 1
        total = len(UPDATE_STEPS)
    status = MaintenanceStatus(
        reason=REASON_UPDATE,
        message=UPDATE_STEP_LABELS[step],
        step=step,
        step_index=index,
        step_total=total,
        sha=sha if sha is not None else (current.sha if current else ""),
        resume_ops=current.resume_ops if current else False,
        ops_message=current.ops_message if current else "",
    )
    write_status(flag, status)
    return status


def leave_update(flag: Path) -> None:
    current = read_status(flag)
    if current is None:
        return
    if current.resume_ops:
        write_status(
            flag,
            MaintenanceStatus(reason=REASON_OPS, message=current.ops_message),
        )
        return
    flag.unlink(missing_ok=True)
