"""GitHub-release prefetch + night-window apply.

``start.sh`` spawns ``scripts/updater.py`` next to Gunicorn (same systemd
cgroup). Tests import the helpers below and never hit GitHub.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import os
import random
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Generator, Iterator, Literal, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common.maintenance import (
    enter_update,
    leave_update,
    update_progress,
)
from common.policy import SitePolicy, get_policy, invalidate_policy_cache

log = logging.getLogger("updater")

DEFAULT_GITHUB_REPO = "nhyzcms/club-management-website"
DRAIN_SECONDS = 10
HEALTH_WAIT_SECONDS = 3
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300
MAX_DOWNLOAD_ATTEMPTS = 8
PROGRESS_LOG_SECONDS = 2.0
PROGRESS_LOG_BYTES = 8 * 1024 * 1024
RETRYABLE_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})
_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.I)
# POSIX hangup; production is Linux. Windows tests have no signal.SIGHUP.
SIGHUP = getattr(signal, "SIGHUP", 1)
# Set by start.sh so apply can SIGHUP Gunicorn (the parent) instead of
# ``systemctl restart club``, which would kill this process with the cgroup.
SPAWNED_ENV = "CLUB_UPDATER_SPAWNED"
GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

ARCHIVE_RE = re.compile(r"^club-([0-9a-f]{7,40})\.tar\.gz$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# GitHub forbids tags that are exactly 40/64 hex; assets stay club-{sha}.tar.gz.
RELEASE_TAG_PREFIX = "club-"

# Live-tree names that must never be replaced or deleted by a release unpack.
# ``.git`` is extra to the plan's list: a clone-based install still has one.
# ``data`` is the unified data root (media / private_media staged inside it;
# see docs/operations/data-root.md); the flat ``media`` / ``private_media``
# entries stay as defence for pre-migration layouts and rollback windows.
SYNC_EXCLUDES = frozenset(
    {
        ".env",
        "db.sqlite3",
        "db.sqlite3-journal",
        "db.sqlite3-wal",
        "db.sqlite3-shm",
        "media",
        "private_media",
        "data",
        "run",
        "backups",
        ".venv",
        ".git",
    }
)

Runner = Callable[..., int]
SleepFn = Callable[[float], None]
NowFn = Callable[[], datetime]


class UpdaterError(Exception):
    """Any apply / download failure the daemon should log and continue from."""


class ApplyError(UpdaterError):
    pass


class WindowClosed(ApplyError):
    """Clock hit the policy window end mid-apply."""


class ApplyInterrupted(ApplyError):
    """Ctrl+C (or equivalent) after the operator chose how to stop."""

    def __init__(self, action: str):
        self.action = action
        super().__init__(f"interrupted ({action})")


InterruptChoice = Literal["continue", "rollback", "abort_clean", "hold"]
InterruptCheck = Callable[[str, bool], InterruptChoice | None]
InterruptReader = Callable[[str], str]

_interrupt_requested = False
_in_rollback = False


def request_interrupt() -> None:
    """Mark a cooperative pause after the current apply step (SIGINT handler)."""
    global _interrupt_requested
    _interrupt_requested = True
    if _in_rollback:
        log.warning("Ctrl+C during rollback ignored until rollback finishes")
        return
    log.warning("Ctrl+C received; will ask what to do after the current step")


def _sigint_handler(signum, frame) -> None:  # noqa: ARG001
    request_interrupt()


def _install_sigint() -> object | None:
    try:
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _sigint_handler)
        return previous
    except (ValueError, OSError):
        return None


def _restore_sigint(previous: object | None) -> None:
    if previous is None:
        return
    try:
        signal.signal(signal.SIGINT, previous)  # type: ignore[arg-type]
    except (ValueError, OSError):
        pass


def interrupt_interactive() -> bool:
    if spawned_from_web():
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def decide_interrupt(
    *,
    files_changed: bool,
    step: str,
    interactive: bool | None = None,
    reader: InterruptReader | None = None,
) -> InterruptChoice:
    """Choose a stable stop: rollback / cancel / hold maintenance / continue."""
    if interactive is None:
        interactive = interrupt_interactive()
    default: InterruptChoice = "rollback" if files_changed else "abort_clean"
    if not interactive:
        log.warning(
            "interrupt at step=%s files_changed=%s; no TTY, using %s",
            step,
            files_changed,
            default,
        )
        return default

    if files_changed:
        prompt = (
            f"\n收到 Ctrl+C。站点文件已经替换（步骤：{step}）。"
            "强行活着退出会留下半套代码。\n"
            "  [r] 回滚到上一版本并恢复这次更新前的数据库备份（推荐）\n"
            "  [c] 继续完成这次更新\n"
            "  [h] 立刻退出，保持维护页（站点继续 503）\n"
            "请选择 [r/c/h]，直接回车 = 回滚： "
        )
        aliases = {
            "": "rollback",
            "r": "rollback",
            "rollback": "rollback",
            "回滚": "rollback",
            "c": "continue",
            "continue": "continue",
            "继续": "continue",
            "h": "hold",
            "hold": "hold",
            "维护": "hold",
        }
    else:
        prompt = (
            f"\n收到 Ctrl+C。当前尚未替换站点文件（步骤：{step}）。\n"
            "  [a] 取消更新并撤下维护页（推荐）\n"
            "  [c] 继续这次更新\n"
            "请选择 [a/c]，直接回车 = 取消： "
        )
        aliases = {
            "": "abort_clean",
            "a": "abort_clean",
            "abort": "abort_clean",
            "取消": "abort_clean",
            "c": "continue",
            "continue": "continue",
            "继续": "continue",
        }

    read = reader or input
    try:
        raw = (read(prompt) or "").strip().lower()
    except (EOFError, KeyboardInterrupt):
        log.warning("interrupt prompt aborted; using %s", default)
        return default
    choice = aliases.get(raw)
    if choice is None:
        log.warning("unrecognized interrupt choice %r; using %s", raw, default)
        return default
    return choice  # type: ignore[return-value]


def _consume_interrupt(
    step: str,
    files_changed: bool,
    *,
    interrupt_check: InterruptCheck | None,
    interactive: bool | None = None,
    reader: InterruptReader | None = None,
) -> None:
    global _interrupt_requested
    choice: InterruptChoice | None = None
    if interrupt_check is not None:
        choice = interrupt_check(step, files_changed)
    elif _interrupt_requested:
        _interrupt_requested = False
        choice = decide_interrupt(
            files_changed=files_changed,
            step=step,
            interactive=interactive,
            reader=reader,
        )
    if choice is None or choice == "continue":
        return
    raise ApplyInterrupted(choice)


class CommandError(ApplyError):
    def __init__(self, argv: Sequence[str], returncode: int):
        self.argv = list(argv)
        self.returncode = returncode
        super().__init__(f"exit {returncode}: {' '.join(self.argv)}")


@dataclass(frozen=True)
class UpdaterPaths:
    root: Path
    run_dir: Path
    backups_dir: Path
    releases_dir: Path
    staging_dir: Path
    lock_file: Path
    applied_file: Path
    maintenance_flag: Path
    db: Path

    @classmethod
    def from_root(cls, root: Path) -> UpdaterPaths:
        root = Path(root).resolve()
        run_dir = root / "run"
        backups = root / "backups"
        return cls(
            root=root,
            run_dir=run_dir,
            backups_dir=backups,
            releases_dir=backups / "releases",
            # Historical path. Apply/rollback now unpack into a fresh
            # backups/staging-* so a leftover undeletable ``staging`` cannot
            # block updates (Errno 13 on the ECS box).
            staging_dir=backups / "staging",
            lock_file=run_dir / "update.lock",
            applied_file=run_dir / "applied-release",
            maintenance_flag=run_dir / "MAINTENANCE",
            db=root / "db.sqlite3",
        )

    def ensure_dirs(self) -> None:
        for p in (self.run_dir, self.releases_dir):
            p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class RemoteRelease:
    sha: str
    tarball_name: str
    tarball_api_url: str
    checksum_api_url: str | None


# ---------------------------------------------------------------------------
# Policy clock
# ---------------------------------------------------------------------------


def policy_tz(policy: SitePolicy):
    name = (policy.update_timezone or "Asia/Shanghai").strip()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        log.warning("unknown timezone %s; using UTC+8", name)
        return timezone(timedelta(hours=8))


def _window_bounds(local: datetime, policy: SitePolicy):
    """Return (start, end) for the window that *could* contain ``local``.

    ``start == end`` hour means an empty window. Overnight (start > end) wraps
    midnight. Bounds are half-open ``[start, end)``.
    """
    start_h = int(policy.update_window_start_hour)
    end_h = int(policy.update_window_end_hour)
    if start_h == end_h:
        return None
    today_start = local.replace(hour=start_h, minute=0, second=0, microsecond=0)
    today_end = local.replace(hour=end_h, minute=0, second=0, microsecond=0)
    if start_h < end_h:
        return today_start, today_end
    if local < today_end:
        return today_start - timedelta(days=1), today_end
    return today_start, today_end + timedelta(days=1)


def in_apply_window(now: datetime, policy: SitePolicy) -> bool:
    local = now.astimezone(policy_tz(policy))
    bounds = _window_bounds(local, policy)
    if bounds is None:
        return False
    start, end = bounds
    return start <= local < end


def before_apply_cutoff(now: datetime, policy: SitePolicy) -> bool:
    """True when ``now`` is inside the window and before the start-apply cutoff."""
    if not in_apply_window(now, policy):
        return False
    local = now.astimezone(policy_tz(policy))
    bounds = _window_bounds(local, policy)
    if bounds is None:
        return False
    _start, end = bounds
    cutoff = end - timedelta(minutes=int(policy.update_apply_cutoff_minutes_before_end))
    return local < cutoff


def can_start_apply(now: datetime, policy: SitePolicy) -> bool:
    """Kill switch + window + cutoff. Manual ``--apply-now`` skips this."""
    if not policy.auto_update_enabled:
        return False
    return before_apply_cutoff(now, policy)


def past_window_end(now: datetime, policy: SitePolicy) -> bool:
    return not in_apply_window(now, policy)


def load_policy() -> SitePolicy:
    """Re-read SiteSettings. locmem is not shared with Gunicorn workers."""
    invalidate_policy_cache()
    return get_policy()


# ---------------------------------------------------------------------------
# Archives on disk
# ---------------------------------------------------------------------------


def archive_sha(path: Path) -> str | None:
    """SHA encoded in ``club-{sha}.tar.gz``. ``None`` for ``.part`` / junk names."""
    name = path.name
    if name.endswith(".part"):
        return None
    match = ARCHIVE_RE.match(name)
    return match.group(1) if match else None


def is_complete_archive(path: Path) -> bool:
    return path.is_file() and archive_sha(path) is not None


def parse_sha256_sidecar(text: str) -> str:
    first = text.strip().split()[0].lower() if text.strip() else ""
    if not SHA256_RE.fullmatch(first):
        raise ValueError("invalid sha256 sidecar")
    return first


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive_checksum(archive: Path, sidecar: Path | None = None) -> None:
    sidecar = sidecar or Path(str(archive) + ".sha256")
    if not sidecar.is_file():
        raise ApplyError(f"missing checksum sidecar {sidecar}")
    expected = parse_sha256_sidecar(sidecar.read_text(encoding="utf-8"))
    actual = file_sha256(archive)
    if expected != actual:
        raise ApplyError(f"sha256 mismatch for {archive.name}: {actual} != {expected}")


def read_applied_sha(paths: UpdaterPaths) -> str | None:
    if not paths.applied_file.is_file():
        return None
    text = paths.applied_file.read_text(encoding="utf-8").strip()
    return text or None


def write_applied_sha(paths: UpdaterPaths, sha: str) -> None:
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    paths.applied_file.write_text(sha.strip() + "\n", encoding="utf-8")


def normalize_sha(ref: str) -> str:
    """Strip ``club-`` prefix from a tag, SHA, or archive stem."""
    text = ref.strip()
    if text.startswith(RELEASE_TAG_PREFIX):
        return text[len(RELEASE_TAG_PREFIX) :]
    return text


def release_tag(sha: str) -> str:
    """GitHub Release tag for a commit SHA (must not be bare 40-hex)."""
    return f"{RELEASE_TAG_PREFIX}{normalize_sha(sha)}"


def complete_archives(releases_dir: Path) -> list[Path]:
    if not releases_dir.is_dir():
        return []
    found = []
    for path in releases_dir.iterdir():
        if is_complete_archive(path):
            found.append(path)
    return found


def archive_for_sha(releases_dir: Path, sha: str) -> Path | None:
    """Exact ``club-{sha}.tar.gz``, or a unique prefix match (min 7 hex chars)."""
    want = normalize_sha(sha)
    if not want:
        return None
    candidate = releases_dir / f"club-{want}.tar.gz"
    if is_complete_archive(candidate):
        return candidate
    if len(want) < 7:
        return None
    matches = []
    for path in complete_archives(releases_dir):
        got = archive_sha(path)
        if got and got.startswith(want):
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    return None


def previous_local_archive(paths: UpdaterPaths) -> Path | None:
    """Newest complete local tarball that is not the currently applied SHA."""
    applied = read_applied_sha(paths)
    newest = None
    newest_mtime = -1.0
    for path in complete_archives(paths.releases_dir):
        sha = archive_sha(path)
        if sha is None or sha == applied:
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest = path
            newest_mtime = mtime
    return newest


def _same_sha(got: str, want: str) -> bool:
    """Exact match, or unique-length prefix (same 7-char floor as ``archive_for_sha``)."""
    if got == want:
        return True
    if len(want) >= 7 and got.startswith(want):
        return True
    if len(got) >= 7 and want.startswith(got):
        return True
    return False


def pending_archive(paths: UpdaterPaths, remote_sha: str | None = None) -> Path | None:
    """Next tarball to apply, or None if already on the target.

    With a GitHub SHA: that archive only — never a different kept rollback
    package. Without: the newest local complete archive, and only if it is
    not already applied. Falling through to "any other local tarball" ping-
    pongs between Latest and the previous release every tick.
    """
    applied = read_applied_sha(paths)
    if remote_sha:
        if applied and _same_sha(applied, remote_sha):
            return None
        return archive_for_sha(paths.releases_dir, remote_sha)

    newest = None
    newest_mtime = -1.0
    for path in complete_archives(paths.releases_dir):
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest = path
            newest_mtime = mtime
    if newest is None:
        return None
    sha = archive_sha(newest)
    if sha is None or sha == applied:
        return None
    return newest


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("could not remove leftover %s", path.name)


def release_sidecars(archive: Path) -> list[Path]:
    """Checksum, incomplete download, and download lock next to a tarball."""
    name = str(archive)
    return [
        Path(name + ".sha256"),
        Path(name + ".part"),
        Path(name + ".part.lock"),
        Path(name + ".sha256.part"),
    ]


def unlink_release_archive(archive: Path) -> None:
    _unlink_quiet(archive)
    for sidecar in release_sidecars(archive):
        _unlink_quiet(sidecar)


def prune_keep_newest(files: Sequence[Path], keep: int) -> list[Path]:
    keep = max(0, int(keep))
    ordered = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    removed = ordered[keep:]
    for path in removed:
        path.unlink(missing_ok=True)
        sidecar = Path(str(path) + ".sha256")
        sidecar.unlink(missing_ok=True)
    return list(removed)


def prune_releases(paths: UpdaterPaths, keep: int) -> list[Path]:
    """Drop oldest complete tarballs, plus each package's sha256 and download lock."""
    keep_n = max(0, int(keep))
    ordered = sorted(
        complete_archives(paths.releases_dir),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = ordered[keep_n:]
    for path in removed:
        unlink_release_archive(path)
    _sweep_orphan_release_sidecars(paths.releases_dir)
    return list(removed)


def _sweep_orphan_release_sidecars(releases_dir: Path) -> None:
    """Remove sha256 / .part / .part.lock whose tarball is already gone."""
    if not releases_dir.is_dir():
        return
    kept = {p.name for p in complete_archives(releases_dir)}
    suffixes = (
        ".tar.gz.sha256",
        ".tar.gz.part.lock",
        ".tar.gz.sha256.part",
        ".tar.gz.part",
    )
    for path in list(releases_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        for suffix in suffixes:
            if not name.endswith(suffix):
                continue
            tarball = name[: -len(suffix)] + ".tar.gz"
            if tarball not in kept:
                _unlink_quiet(path)
            break


def prune_db_backups(paths: UpdaterPaths, keep: int) -> list[Path]:
    if not paths.backups_dir.is_dir():
        return []
    snaps = [
        p
        for pattern in ("db-*.sqlite3", "db-*.pg.sql")
        for p in paths.backups_dir.glob(pattern)
        if p.is_file()
    ]
    return prune_keep_newest(snaps, keep)


# ---------------------------------------------------------------------------
# Unpack / rsync-equivalent / database snapshots
# ---------------------------------------------------------------------------


STAGING_PREFIX = "staging-"


def make_staging(parent: Path) -> Path:
    """Fresh directory under ``parent``. Never reuses a leftover ``staging`` path."""
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=parent))


def remove_tree(path: Path, *, ignore_errors: bool = False) -> None:
    """``rmtree`` that chmod's read-only entries first (tarball 0555 dirs)."""

    def onexc(func: Callable[..., Any], p: str, exc: BaseException) -> None:
        try:
            os.chmod(p, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
        except OSError:
            if ignore_errors:
                return
            raise exc
        try:
            func(p)
        except OSError:
            if ignore_errors:
                return
            raise

    if not path.exists() and not path.is_symlink():
        return
    # Do not pass ignore_errors to shutil: it would replace onexc with a no-op
    # and skip the chmod retry (Python 3.12+).
    shutil.rmtree(path, onexc=onexc)


@contextmanager
def staging_workspace(parent: Path) -> Iterator[Path]:
    staging = make_staging(parent)
    try:
        yield staging
    finally:
        try:
            remove_tree(staging, ignore_errors=True)
        except OSError:
            log.warning("could not remove staging %s", staging, exc_info=True)


def unpack_archive(archive: Path, staging: Path) -> None:
    """Extract a complete tarball into ``staging`` (replaced). Never unpack ``.part``."""
    if archive_sha(archive) is None:
        raise ApplyError(f"refusing to unpack incomplete or unnamed archive: {archive.name}")
    if staging.exists():
        remove_tree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(staging, filter="data")


def _rel_top(rel: Path) -> str | None:
    return rel.parts[0] if rel.parts else None


def sync_tree(
    src: Path,
    dest: Path,
    *,
    excludes: frozenset[str] = SYNC_EXCLUDES,
) -> None:
    """Mirror ``src`` onto ``dest``, never touching excluded live-tree names.

    Equivalent to ``rsync -a --delete`` with those ``--exclude`` entries.
    """
    src = src.resolve()
    dest = dest.resolve()
    if not src.is_dir():
        raise FileNotFoundError(src)
    dest.mkdir(parents=True, exist_ok=True)

    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel_dir = Path(dirpath).relative_to(src)
        top = _rel_top(rel_dir)
        if top in excludes:
            dirnames.clear()
            continue
        dest_dir = dest / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            rel = Path(name) if rel_dir == Path(".") else rel_dir / name
            if _rel_top(rel) in excludes:
                continue
            shutil.copy2(Path(dirpath) / name, dest_dir / name)

    for dirpath, dirnames, filenames in os.walk(dest, topdown=True, followlinks=False):
        rel_dir = Path(dirpath).relative_to(dest)
        if _rel_top(rel_dir) in excludes:
            dirnames.clear()
            continue
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in excludes]
        for name in filenames:
            rel = Path(name) if rel_dir == Path(".") else rel_dir / name
            if _rel_top(rel) in excludes:
                continue
            if not (src / rel).is_file():
                (Path(dirpath) / name).unlink(missing_ok=True)
        for name in list(dirnames):
            rel = Path(name) if rel_dir == Path(".") else rel_dir / name
            if _rel_top(rel) in excludes:
                continue
            if not (src / rel).is_dir():
                shutil.rmtree(Path(dirpath) / name, ignore_errors=True)
                dirnames.remove(name)


def backup_sqlite(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        return
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def restore_sqlite(snapshot: Path, db: Path) -> None:
    if not snapshot.is_file():
        return
    for suffix in ("-journal", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    shutil.copy2(snapshot, db)


# ---- PostgreSQL snapshots (used when DATABASES.default is PostgreSQL) ----


def find_pg_tool(name: str) -> str | None:
    """pg_dump / psql: PATH first, then PGDG's versioned dirs (/usr/pgsql-*/bin)."""
    found = shutil.which(name)
    if found:
        return found
    matches = glob.glob(f"/usr/pgsql-*/bin/{name}")
    if not matches:
        return None

    def version_key(path: str) -> int:
        matched = re.search(r"pgsql-(\d+)", path)
        return int(matched.group(1)) if matched else 0

    return sorted(matches, key=version_key)[-1]


def database_kind() -> str:
    """``"postgres"`` when the default DB is PostgreSQL, otherwise ``"sqlite"``."""
    from django.conf import settings as dj_settings

    engine = str((dj_settings.DATABASES.get("default") or {}).get("ENGINE", ""))
    return "postgres" if "postgresql" in engine else "sqlite"


def db_snapshot_name(stamp: str) -> str:
    return f"db-{stamp}.pg.sql" if database_kind() == "postgres" else f"db-{stamp}.sqlite3"


def _pg_db() -> dict:
    from django.conf import settings as dj_settings

    return dict(dj_settings.DATABASES.get("default") or {})


def postgres_env() -> dict:
    """Child env for psql/pg_dump: inherit process env + PGPASSWORD."""
    env = dict(os.environ)
    password = _pg_db().get("PASSWORD")
    if password:
        env["PGPASSWORD"] = str(password)
    return env


def pg_dump_command(dest: Path) -> list[str]:
    """Plain-SQL dump: restorable with ``psql -f``; drops objects first (--clean)."""
    db = _pg_db()
    exe = find_pg_tool("pg_dump") or "pg_dump"
    return [
        exe,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-acl",
        "-h",
        str(db.get("HOST") or "127.0.0.1"),
        "-p",
        str(db.get("PORT") or 5432),
        "-U",
        str(db.get("USER") or ""),
        "-d",
        str(db.get("NAME") or ""),
        "-f",
        str(dest),
    ]


def pg_restore_command(snapshot: Path) -> list[str]:
    db = _pg_db()
    exe = find_pg_tool("psql") or "psql"
    return [
        exe,
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        str(db.get("HOST") or "127.0.0.1"),
        "-p",
        str(db.get("PORT") or 5432),
        "-U",
        str(db.get("USER") or ""),
        "-d",
        str(db.get("NAME") or ""),
        "-f",
        str(snapshot),
    ]


def backup_postgres(dest: Path, run: Runner) -> None:
    """Snapshot PostgreSQL to a plain-SQL file before an apply (rollback source)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if find_pg_tool("pg_dump") is None:
        raise ApplyError(
            "pg_dump not found (PATH or /usr/pgsql-*/bin); "
            "install the PostgreSQL client tools to enable update snapshots"
        )
    run(pg_dump_command(dest), env=postgres_env())
    if not dest.is_file() or dest.stat().st_size == 0:
        raise ApplyError(f"pg_dump produced an empty snapshot at {dest}")


def restore_postgres(snapshot: Path, run: Runner) -> None:
    """Restore a plain-SQL pg_dump snapshot created with --clean --if-exists."""
    if find_pg_tool("psql") is None:
        raise ApplyError("psql not found (PATH or /usr/pgsql-*/bin); cannot restore snapshot")
    run(pg_restore_command(snapshot), env=postgres_env())


def set_maintenance(paths: UpdaterPaths, on: bool, *, sha: str = "") -> None:
    """Back-compat wrapper: enter/leave update intercept (not ops)."""
    if on:
        enter_update(paths.maintenance_flag, sha=sha)
    else:
        leave_update(paths.maintenance_flag)


# ---------------------------------------------------------------------------
# flock
# ---------------------------------------------------------------------------


def _lock_exclusive(fh, *, blocking: bool) -> None:
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is not None:
        flags = fcntl.LOCK_EX # type: ignore
        if not blocking:
            flags |= fcntl.LOCK_NB # type: ignore
        try:
            fcntl.flock(fh.fileno(), flags) # type: ignore
        except BlockingIOError:
            raise
        except OSError as exc:
            raise BlockingIOError("update lock held") from exc
        return
    import msvcrt

    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
    try:
        msvcrt.locking(fh.fileno(), mode, 1)
    except OSError as exc:
        raise BlockingIOError("update lock held") from exc


def _lock_release(fh) -> None:
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is not None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN) # type: ignore
        except OSError:
            pass
        return
    try:
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def update_lock(lock_path: Path, *, blocking: bool = True) -> Iterator[None]:
    """Exclusive flock on ``lock_path`` (fcntl on Unix, msvcrt on Windows)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        fh.seek(0)
        _lock_exclusive(fh, blocking=blocking)
        yield
    finally:
        try:
            _lock_release(fh)
        finally:
            fh.close()


@contextmanager
def _hold_download_lock(part: Path) -> Iterator[None]:
    """Serialize writers of the same ``.part`` across updater processes.

    ``--apply-now`` and the ``start.sh`` daemon share ``backups/releases``.
    Without this lock both resume the same file and the local copy can grow
    past the remote size (HTTP 416 on the next Range request).
    """
    lock_path = Path(str(part) + ".lock")
    acquired = False
    try:
        with update_lock(lock_path, blocking=False):
            acquired = True
            yield
            return
    except BlockingIOError:
        if acquired:
            raise
    log.info("waiting for another process to finish downloading %s", part.name)
    with update_lock(lock_path, blocking=True):
        yield


def _verified_complete_archive(dest: Path) -> Path | None:
    if not is_complete_archive(dest):
        return None
    sidecar = Path(str(dest) + ".sha256")
    try:
        if sidecar.is_file():
            verify_archive_checksum(dest, sidecar)
            return dest
    except ApplyError:
        log.warning("existing %s failed checksum; re-downloading", dest.name)
        dest.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
    return None


# ---------------------------------------------------------------------------
# GitHub HTTP
# ---------------------------------------------------------------------------


class _StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Drop Authorization when GitHub 302s the asset to S3."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urlparse(new.full_url).netloc != urlparse(req.full_url).netloc:
            for header in ("Authorization", "authorization"):
                try:
                    new.remove_header(header)
                except KeyError:
                    pass
        return new


def _github_headers(token: str, *, accept: str) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "club-updater",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_StripAuthOnRedirect)


def _format_bytes(n: float) -> str:
    n = float(n)
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KiB"
    return f"{n / (1024 ** 2):.1f} MiB"


def _format_progress(name: str, copied: int, total: int | None, speed: float) -> str:
    size = _format_bytes(copied)
    if total and total > 0:
        pct = min(100.0, 100.0 * copied / total)
        size = f"{_format_bytes(copied)}/{_format_bytes(total)} ({pct:.0f}%)"
    rate = f" {_format_bytes(speed)}/s" if speed > 0 else ""
    return f"{name}: {size}{rate}"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP
    if isinstance(exc, UpdaterError):
        return any(f"HTTP {code}" in str(exc) for code in RETRYABLE_HTTP)
    return isinstance(exc, (urllib.error.URLError, TimeoutError, OSError, ConnectionError))


def github_json(url: str, token: str, *, timeout: int = 60, sleep: SleepFn = time.sleep) -> Any:
    last_error: Exception | None = None
    for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
        req = urllib.request.Request(
            url,
            headers=_github_headers(token, accept="application/vnd.github+json"),
        )
        retryable = False
        try:
            with _opener().open(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            last_error = UpdaterError(f"GitHub HTTP {exc.code} for {url}")
            retryable = _is_retryable(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = UpdaterError(f"GitHub request failed for {url}: {exc}")
            retryable = True
        if (not retryable) or attempt + 1 >= MAX_DOWNLOAD_ATTEMPTS:
            raise last_error from None
        delay = retry_delay(attempt)
        log.warning(
            "GitHub API attempt %s/%s failed: %s; retry in %.0fs",
            attempt + 1,
            MAX_DOWNLOAD_ATTEMPTS,
            last_error,
            delay,
        )
        sleep(delay)
    raise last_error  # type: ignore # pragma: no cover


def _resp_header(resp, name: str) -> str | None:
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return None if value is None else str(value)


def _header_int(resp, name: str) -> int | None:
    raw = _resp_header(resp, name)
    if raw is None:
        return None
    text = raw.strip()
    return int(text) if text.isdigit() else None


def _parse_content_range(header: str | None) -> tuple[int, int, int | None] | None:
    if not header:
        return None
    matched = _CONTENT_RANGE_RE.match(header.strip())
    if not matched:
        return None
    start, end, total_s = int(matched.group(1)), int(matched.group(2)), matched.group(3)
    return start, end, (None if total_s == "*" else int(total_s))


def github_download(
    url: str,
    dest: Path,
    token: str,
    *,
    timeout: int = 300,
) -> None:
    """Stream ``url`` to ``dest``, resuming with ``Range`` when a partial file exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.is_file() else 0
    headers = _github_headers(token, accept="application/octet-stream")
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        log.info(
            "resume: %s has %s on disk; requesting Range: bytes=%s-",
            dest.name,
            _format_bytes(existing),
            existing,
        )
    req = urllib.request.Request(url, headers=headers)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode() or 200)
            mode = "wb"
            if existing > 0 and status == 200:
                log.info(
                    "resume rejected: HTTP 200 (server ignored Range) for %s; restarting from 0",
                    dest.name,
                )
                existing = 0
            elif existing > 0 and status == 206:
                parsed = _parse_content_range(_resp_header(resp, "Content-Range"))
                if parsed is None or parsed[0] != existing:
                    dest.unlink(missing_ok=True)
                    raise UpdaterError(
                        f"unexpected Content-Range for {url}: {_resp_header(resp, 'Content-Range')}"
                    )
                remaining = (
                    parsed[2] - parsed[0] if parsed[2] is not None
                    else parsed[1] - parsed[0] + 1
                )
                log.info(
                    "resume accepted: HTTP 206 Content-Range %s; appending %s to %s",
                    _resp_header(resp, "Content-Range"),
                    _format_bytes(remaining),
                    dest.name,
                )
                mode = "ab"
            elif existing > 0:
                raise UpdaterError(f"GitHub HTTP {status} downloading {url}")

            total: int | None = None
            if status == 206:
                parsed = _parse_content_range(_resp_header(resp, "Content-Range"))
                if parsed is not None and parsed[2] is not None:
                    total = parsed[2]
                else:
                    remaining = _header_int(resp, "Content-Length")
                    if remaining is not None:
                        total = existing + remaining
            else:
                total = _header_int(resp, "Content-Length")

            copied = existing if mode == "ab" else 0
            last_log = time.monotonic()
            last_copied = copied
            started = last_log
            log.info(
                "downloading %s (%s)",
                dest.name,
                _format_bytes(total) if total else "unknown size",
            )
            with open(dest, mode) as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    copied += len(chunk)
                    now = time.monotonic()
                    if now - last_log >= PROGRESS_LOG_SECONDS or copied - last_copied >= PROGRESS_LOG_BYTES:
                        speed = (copied - last_copied) / max(now - last_log, 1e-6)
                        log.info("%s", _format_progress(dest.name, copied, total, speed))
                        last_log = now
                        last_copied = copied
            if total is not None and copied < total:
                log.warning(
                    "incomplete download of %s: %s != %s; keeping partial for resume",
                    dest.name,
                    _format_bytes(copied),
                    _format_bytes(total),
                )
                raise UpdaterError(
                    f"incomplete download of {dest.name}: "
                    f"{_format_bytes(copied)} != {_format_bytes(total)}; "
                    "keeping partial for resume"
                )
            if total is not None and copied > total:
                dest.unlink(missing_ok=True)
                raise UpdaterError(
                    f"download of {dest.name} exceeded Content-Length: "
                    f"{_format_bytes(copied)} > {_format_bytes(total)}"
                )
            elapsed = max(time.monotonic() - started, 1e-6)
            if mode == "ab" and existing > 0:
                log.info(
                    "resume finished: %s now %s (appended %s in %.1fs)",
                    dest.name,
                    _format_bytes(copied),
                    _format_bytes(copied - existing),
                    elapsed,
                )
            else:
                log.info(
                    "downloaded %s %s in %.1fs (%s/s)",
                    dest.name,
                    _format_bytes(copied),
                    elapsed,
                    _format_bytes(copied / elapsed),
                )
    except urllib.error.HTTPError as exc:
        if existing > 0:
            log.warning(
                "resume: HTTP %s for %s after %s on disk%s",
                exc.code,
                dest.name,
                _format_bytes(existing),
                "; discarding partial" if exc.code in {401, 403, 404, 410, 416} else "; keeping partial for retry",
            )
        if exc.code in {401, 403, 404, 410, 416}:
            dest.unlink(missing_ok=True)
        raise UpdaterError(f"GitHub HTTP {exc.code} downloading {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        kept = dest.stat().st_size if dest.is_file() else 0
        if kept:
            log.warning(
                "download failed for %s after %s; keeping partial for resume: %s",
                dest.name,
                _format_bytes(kept),
                exc,
            )
        raise UpdaterError(f"download failed for {url}: {exc}") from exc


def parse_release_assets(payload: dict) -> RemoteRelease | None:
    assets = payload.get("assets") or []
    tarball = None
    checksum = None
    for asset in assets:
        name = asset.get("name") or ""
        if name.endswith(".tar.gz.sha256"):
            checksum = asset
        elif ARCHIVE_RE.match(name):
            tarball = asset
    if tarball is None:
        return None
    sha = archive_sha(Path(tarball["name"]))
    if sha is None:
        return None
    api_url = tarball.get("url") or ""
    if not api_url:
        return None
    checksum_url = None
    if checksum and checksum.get("url"):
        checksum_url = checksum["url"]
    return RemoteRelease(
        sha=sha,
        tarball_name=tarball["name"],
        tarball_api_url=api_url,
        checksum_api_url=checksum_url,
    )


def retry_delay(
    attempt: int,
    *,
    base: float = RETRY_BASE_SECONDS,
    cap: float = RETRY_MAX_SECONDS,
    jitter: Callable[[], float] | None = None,
) -> float:
    """Exponential backoff with jitter. ``attempt`` is 0-based."""
    raw = min(cap, float(base) * (2 ** attempt))
    roll = random.random() if jitter is None else jitter()
    return raw * (0.5 + 0.5 * roll)


def github_token() -> str:
    from django.conf import settings

    return (getattr(settings, "UPDATE_GITHUB_TOKEN", None) or os.environ.get("UPDATE_GITHUB_TOKEN") or "").strip()


def github_repo() -> str:
    from django.conf import settings

    raw = (
        getattr(settings, "UPDATE_GITHUB_REPO", None)
        or os.environ.get("UPDATE_GITHUB_REPO")
        or DEFAULT_GITHUB_REPO
    )
    return raw.strip() or DEFAULT_GITHUB_REPO


def fetch_releases(
    repo: str,
    token: str,
    *,
    get_json: Callable[[str, str], Any] | None = None,
) -> list[RemoteRelease]:
    """Newest-first GitHub releases that have a ``club-{sha}.tar.gz`` asset."""
    fetch = get_json or github_json
    url = f"{GITHUB_API}/repos/{repo}/releases?per_page=30"
    try:
        payload = fetch(url, token)
    except UpdaterError as exc:
        log.warning("release list failed: %s", exc)
        return []
    if not isinstance(payload, list):
        return []
    found: list[RemoteRelease] = []
    for item in payload:
        if isinstance(item, dict):
            parsed = parse_release_assets(item)
            if parsed is not None:
                found.append(parsed)
    return found


def fetch_release(
    repo: str,
    token: str,
    *,
    tag: str | None = None,
    get_json: Callable[[str, str], Any] | None = None,
) -> RemoteRelease | None:
    fetch = get_json or github_json
    if tag:
        want = normalize_sha(tag)
        url = f"{GITHUB_API}/repos/{repo}/releases/tags/{release_tag(want)}"
        try:
            payload = fetch(url, token)
            if isinstance(payload, dict):
                parsed = parse_release_assets(payload)
                if parsed is not None:
                    return parsed
        except UpdaterError as exc:
            log.warning("release tag lookup failed: %s", exc)
        if len(want) >= 7:
            for remote in fetch_releases(repo, token, get_json=fetch):
                if remote.sha.startswith(want):
                    return remote
        return None
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    try:
        payload = fetch(url, token)
    except UpdaterError as exc:
        log.warning("release lookup failed: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None
    return parse_release_assets(payload)


def download_release(
    remote: RemoteRelease,
    paths: UpdaterPaths,
    token: str,
    *,
    download: Callable[..., None] | None = None,
    sleep: SleepFn = time.sleep,
) -> Path:
    """Download tarball + sidecar to ``.part``, verify, then rename.

    Incomplete ``.part`` files are kept and resumed with HTTP Range. Apply never
    unpacks a ``.part``; only a checksum-ok rename becomes a usable archive.
    Exclusive flock on ``*.part.lock`` so a manual ``--apply-now`` cannot
    resume the same file the daemon is still writing.
    """
    dest = paths.releases_dir / remote.tarball_name
    paths.releases_dir.mkdir(parents=True, exist_ok=True)
    part = Path(str(dest) + ".part")
    sidecar_dest = Path(str(dest) + ".sha256")
    sidecar_part = Path(str(sidecar_dest) + ".part")

    with _hold_download_lock(part):
        result = _download_release_locked(
            remote,
            dest,
            part,
            sidecar_dest,
            sidecar_part,
            token,
            download=download,
            sleep=sleep,
        )
    Path(str(part) + ".lock").unlink(missing_ok=True)
    return result


def _download_release_locked(
    remote: RemoteRelease,
    dest: Path,
    part: Path,
    sidecar_dest: Path,
    sidecar_part: Path,
    token: str,
    *,
    download: Callable[..., None] | None,
    sleep: SleepFn,
) -> Path:
    existing = _verified_complete_archive(dest)
    if existing is not None:
        return existing

    if remote.checksum_api_url is None:
        raise UpdaterError(f"release {remote.sha} has no sha256 sidecar")

    save = download or github_download
    last_error: Exception | None = None
    for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
        log.info(
            "download %s attempt %s/%s",
            remote.tarball_name,
            attempt + 1,
            MAX_DOWNLOAD_ATTEMPTS,
        )
        sidecar_part.unlink(missing_ok=True)
        already = part.stat().st_size if part.is_file() else 0
        if already:
            log.info(
                "resume: %s already has %s from a previous attempt",
                part.name,
                _format_bytes(already),
            )
        try:
            save(remote.checksum_api_url, sidecar_part, token)
            save(remote.tarball_api_url, part, token)
            expected = parse_sha256_sidecar(sidecar_part.read_text(encoding="utf-8"))
            actual = file_sha256(part)
            if expected != actual:
                raise ApplyError(f"downloaded sha256 mismatch: {actual} != {expected}")
            sidecar_part.replace(sidecar_dest)
            part.replace(dest)
            log.info("saved %s", dest.name)
            return dest
        except (UpdaterError, ApplyError, OSError, urllib.error.URLError) as exc:
            last_error = exc
            delay = retry_delay(attempt) if attempt + 1 < MAX_DOWNLOAD_ATTEMPTS else 0.0
            log.warning(
                "download attempt %s/%s failed: %s%s",
                attempt + 1,
                MAX_DOWNLOAD_ATTEMPTS,
                exc,
                f"; retry in {delay:.0f}s" if delay else "",
            )
            sidecar_part.unlink(missing_ok=True)
            if isinstance(exc, ApplyError):
                log.warning("checksum failed; discarding %s to restart from 0", part.name)
                part.unlink(missing_ok=True)
            elif part.is_file() and part.stat().st_size > 0:
                log.info(
                    "keeping %s (%s) to resume on the next attempt",
                    part.name,
                    _format_bytes(part.stat().st_size),
                )
            if delay:
                sleep(delay)
    raise UpdaterError(f"download failed after {MAX_DOWNLOAD_ATTEMPTS} attempts: {last_error}")


def poll_and_download(
    paths: UpdaterPaths,
    token: str,
    repo: str,
    *,
    get_json: Callable[[str, str], Any] | None = None,
    download: Callable[..., None] | None = None,
    sleep: SleepFn = time.sleep,
) -> RemoteRelease | None:
    """Fetch latest (and applied SHA, for rollback insurance). Return latest remote."""
    latest = fetch_release(repo, token, get_json=get_json)
    if latest is None:
        return None
    download_release(latest, paths, token, download=download, sleep=sleep)

    applied = read_applied_sha(paths)
    if applied and applied != latest.sha and archive_for_sha(paths.releases_dir, applied) is None:
        previous = fetch_release(repo, token, tag=applied, get_json=get_json)
        if previous is not None:
            try:
                download_release(previous, paths, token, download=download, sleep=sleep)
            except UpdaterError:
                log.warning("could not prefetch applied-release %s for rollback", applied)
    return latest


# ---------------------------------------------------------------------------
# Apply / rollback
# ---------------------------------------------------------------------------


def find_uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    home = Path.home()
    candidates = [home / ".local" / "bin" / "uv", home / ".cargo" / "bin" / "uv"]
    if os.name == "nt":
        candidates = [c.with_suffix(".exe") for c in candidates] + candidates
    for path in candidates:
        if path.is_file():
            return str(path)
    return "uv"


def make_runner(cwd: Path) -> Runner:
    extra: dict = {}
    if os.name != "nt":
        extra["start_new_session"] = True
    else:
        create_new = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if create_new:
            extra["creationflags"] = create_new

    def run(
        argv: Sequence[str], *, check: bool = True, env: dict | None = None
    ) -> int:
        log.info("+ %s", " ".join(str(a) for a in argv))
        completed = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, **extra)
        if check and completed.returncode != 0:
            raise CommandError(argv, completed.returncode)
        return completed.returncode

    return run


def _service_active(run: Runner, service: str) -> bool:
    return run(["sudo", "systemctl", "is-active", "--quiet", service], check=False) == 0


def spawned_from_web() -> bool:
    return os.environ.get(SPAWNED_ENV) == "1"


def reload_web(run: Runner, service: str) -> None:
    """Reload Gunicorn workers without stopping the systemd unit (or this updater).

    When spawned by start.sh, Gunicorn is our parent (same PID after ``exec``).
    ``systemctl restart club`` would kill the whole cgroup, including us.
    Manual ``--apply-now`` still uses ``systemctl restart``.
    """
    if spawned_from_web():
        ppid = os.getppid()
        if ppid > 1:
            log.info("SIGHUP gunicorn master pid=%s", ppid)
            os.kill(ppid, SIGHUP)
            return
        log.warning("%s set but ppid=%s; falling back to systemctl restart", SPAWNED_ENV, ppid)
    run(["sudo", "systemctl", "restart", service])


def reexec_updater(paths: UpdaterPaths) -> None:
    """Replace this process with the on-disk updater (new code after unpack)."""
    python = paths.root / ".venv" / "bin" / "python"
    script = paths.root / "scripts" / "updater.py"
    if not python.is_file() or not script.is_file():
        log.warning("skip re-exec: missing %s or %s", python, script)
        return
    log.info("re-exec %s %s", python, script)
    os.execv(str(python), [str(python), str(script)])


def _check_window(now: datetime, policy: SitePolicy, *, respect_window: bool) -> None:
    if respect_window and past_window_end(now, policy):
        raise WindowClosed("apply window closed")


def rollback_release(
    paths: UpdaterPaths,
    *,
    previous_archive: Path | None,
    db_snapshot: Path | None,
    previous_sha: str | None,
    restore_files: bool,
    run: Runner,
    sleep: SleepFn,
    service: str,
) -> None:
    global _in_rollback
    log.error("rolling back to %s", previous_sha or "current files + db snapshot")
    _in_rollback = True
    try:
        update_progress(paths.maintenance_flag, "rollback")
        if restore_files and previous_archive is not None and is_complete_archive(previous_archive):
            with staging_workspace(paths.backups_dir) as staging:
                unpack_archive(previous_archive, staging)
                sync_tree(staging, paths.root)
        elif restore_files:
            log.error("no previous tarball; leaving files as they are")
        if db_snapshot is not None and db_snapshot.is_file():
            if db_snapshot.name.endswith(".pg.sql"):
                restore_postgres(db_snapshot, run)
            else:
                restore_sqlite(db_snapshot, paths.db)
            log.info("restored DB snapshot %s", db_snapshot)
        uv = find_uv()
        run([uv, "sync", "--frozen"])
        run([uv, "run", "python", "manage.py", "collectstatic", "--noinput"])
        reload_web(run, service)
        sleep(HEALTH_WAIT_SECONDS)
        healthy = _service_active(run, service)
        if previous_sha:
            write_applied_sha(paths, previous_sha)
        if healthy:
            leave_update(paths.maintenance_flag)
        else:
            log.error("rollback service unhealthy; leaving MAINTENANCE on")
    except Exception:
        log.exception("rollback failed; leaving MAINTENANCE on")
    finally:
        _in_rollback = False


def apply_release(
    paths: UpdaterPaths,
    archive: Path,
    policy: SitePolicy,
    *,
    run: Runner | None = None,
    sleep: SleepFn = time.sleep,
    now_fn: NowFn | None = None,
    respect_window: bool = True,
    service: str = "club",
    drain_seconds: float = DRAIN_SECONDS,
    reexec: bool = False,
    interrupt_check: InterruptCheck | None = None,
) -> str:
    """Apply a complete local tarball. On failure, window end, or confirmed Ctrl+C, roll back."""
    global _interrupt_requested
    sha = archive_sha(archive)
    if sha is None:
        raise ApplyError(f"refusing to apply incomplete archive {archive.name}")
    sidecar = Path(str(archive) + ".sha256")
    if sidecar.is_file():
        verify_archive_checksum(archive, sidecar)

    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    run = run or make_runner(paths.root)
    previous_sha = read_applied_sha(paths)
    previous = archive_for_sha(paths.releases_dir, previous_sha) if previous_sha else None
    if previous_sha and previous is None:
        log.warning(
            "applied-release %s has no local tarball; file rollback may be impossible",
            previous_sha,
        )

    stamp = now_fn().strftime("%Y%m%d-%H%M%S")
    db_bak = paths.backups_dir / db_snapshot_name(stamp)
    files_changed = False
    uv = find_uv()
    prev_sigint = _install_sigint()
    _interrupt_requested = False

    def checkpoint(step: str) -> None:
        _consume_interrupt(step, files_changed, interrupt_check=interrupt_check)

    enter_update(paths.maintenance_flag, sha=sha)
    try:
        try:
            sleep(drain_seconds)
            checkpoint("drain")
            update_progress(paths.maintenance_flag, "backup", sha=sha)
            if database_kind() == "postgres":
                backup_postgres(db_bak, run)
            else:
                backup_sqlite(paths.db, db_bak)
            # 备份含密码哈希 / 邮箱 / 业务数据：只给属主读写（审计 M-10）。
            try:
                os.chmod(db_bak, 0o600)
            except OSError:
                log.warning("chmod 0600 failed for %s", db_bak)
            try:
                prune_db_backups(paths, policy.update_db_backup_keep)
            except OSError:
                log.warning("prune of old DB snapshots failed", exc_info=True)
            checkpoint("backup")
            _check_window(now_fn(), policy, respect_window=respect_window)
            update_progress(paths.maintenance_flag, "unpack", sha=sha)
            with staging_workspace(paths.backups_dir) as staging:
                unpack_archive(archive, staging)
                checkpoint("unpack")
                _check_window(now_fn(), policy, respect_window=respect_window)
                update_progress(paths.maintenance_flag, "sync", sha=sha)
                sync_tree(staging, paths.root)
            files_changed = True
            checkpoint("sync")
            _check_window(now_fn(), policy, respect_window=respect_window)
            update_progress(paths.maintenance_flag, "deps", sha=sha)
            run([uv, "sync", "--frozen"])
            checkpoint("deps")
            _check_window(now_fn(), policy, respect_window=respect_window)
            update_progress(paths.maintenance_flag, "migrate", sha=sha)
            run([uv, "run", "python", "manage.py", "migrate"])
            checkpoint("migrate")
            _check_window(now_fn(), policy, respect_window=respect_window)
            update_progress(paths.maintenance_flag, "collectstatic", sha=sha)
            run([uv, "run", "python", "manage.py", "collectstatic", "--noinput"])
            checkpoint("collectstatic")
            _check_window(now_fn(), policy, respect_window=respect_window)
            update_progress(paths.maintenance_flag, "reload", sha=sha)
            reload_web(run, service)
            sleep(HEALTH_WAIT_SECONDS)
            if not _service_active(run, service):
                raise ApplyError(f"{service} is not active after reload")
            write_applied_sha(paths, sha)
            try:
                os.utime(archive, None)
            except OSError:
                pass
            try:
                prune_releases(paths, policy.update_release_keep)
            except OSError:
                log.warning("prune of old release tarballs failed", exc_info=True)
        except ApplyInterrupted as exc:
            log.warning("apply of %s interrupted: %s", sha, exc.action)
            if exc.action == "rollback":
                rollback_release(
                    paths,
                    previous_archive=previous,
                    db_snapshot=db_bak if db_bak.is_file() else None,
                    previous_sha=previous_sha,
                    restore_files=files_changed,
                    run=run,
                    sleep=sleep,
                    service=service,
                )
            elif exc.action == "abort_clean":
                leave_update(paths.maintenance_flag)
            else:
                log.error("leaving MAINTENANCE on at operator request")
            raise
        except Exception as exc:
            log.exception("apply of %s failed: %s", sha, exc)
            rollback_release(
                paths,
                previous_archive=previous,
                db_snapshot=db_bak if db_bak.is_file() else None,
                previous_sha=previous_sha,
                restore_files=files_changed,
                run=run,
                sleep=sleep,
                service=service,
            )
            raise

        leave_update(paths.maintenance_flag)
        log.info("applied %s", sha)
        if reexec:
            reexec_updater(paths)
        return sha
    finally:
        _restore_sigint(prev_sigint)
        _interrupt_requested = False


def _ensure_uv_on_path() -> None:
    home = Path.home()
    extra = [str(home / ".local" / "bin"), str(home / ".cargo" / "bin")]
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for item in reversed(extra):
        if item and item not in parts:
            parts.insert(0, item)
    os.environ["PATH"] = os.pathsep.join(parts)


def _configure_logging() -> None:
    """Always attach updater logs to stdout (systemd/journalctl -u club)."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(line_buffering=True)
        except OSError:
            pass
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    log.setLevel(logging.INFO)
    if not any(
        isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout
        for h in log.handlers
    ):
        log.addHandler(handler)
    log.propagate = False


def _apply_pending(
    paths: UpdaterPaths,
    policy: SitePolicy,
    *,
    remote_sha: str | None,
    respect_window: bool,
    service: str,
    blocking_lock: bool,
    run: Runner | None = None,
    sleep: SleepFn = time.sleep,
    now_fn: NowFn | None = None,
    reexec: bool = False,
) -> str | None:
    archive = pending_archive(paths, remote_sha=remote_sha)
    if archive is None:
        return None
    try:
        with update_lock(paths.lock_file, blocking=blocking_lock):
            if respect_window and not can_start_apply(
                (now_fn or (lambda: datetime.now(timezone.utc)))(),
                policy,
            ):
                return None
            return apply_release(
                paths,
                archive,
                policy,
                run=run,
                sleep=sleep,
                now_fn=now_fn,
                respect_window=respect_window,
                service=service,
                reexec=reexec,
            )
    except BlockingIOError:
        log.info("skip apply: %s held", paths.lock_file)
        return None


def poll_tick(
    paths: UpdaterPaths,
    policy: SitePolicy,
    *,
    service: str = "club",
    run: Runner | None = None,
    sleep: SleepFn = time.sleep,
    now_fn: NowFn | None = None,
    get_json=None,
    download=None,
    apply: bool = True,
    reexec: bool = False,
) -> RemoteRelease | None:
    """One loop iteration: maybe download, maybe apply. Used by the daemon and tests."""
    if not policy.auto_update_enabled:
        log.info("auto_update_enabled=false; skip download and apply")
        return None
    token = github_token()
    repo = github_repo()
    remote = None
    if token:
        try:
            remote = poll_and_download(
                paths,
                token,
                repo,
                get_json=get_json,
                download=download,
                sleep=sleep,
            )
        except UpdaterError:
            log.exception("poll/download failed")
    else:
        log.warning("UPDATE_GITHUB_TOKEN empty; skip download")

    if not apply:
        return remote
    now = (now_fn or (lambda: datetime.now(timezone.utc)))()
    if not can_start_apply(now, policy):
        return remote
    _apply_pending(
        paths,
        policy,
        remote_sha=remote.sha if remote else None,
        respect_window=True,
        service=service,
        blocking_lock=False,
        run=run,
        sleep=sleep,
        now_fn=now_fn,
        reexec=reexec,
    )
    return remote


def local_archive_for_ref(paths: UpdaterPaths, target: str) -> Path | None:
    """A complete ``club-*.tar.gz`` already on disk: path, filename, or SHA/tag."""
    raw = target.strip()
    if not raw:
        return None
    candidate = Path(raw)
    looks_like_path = (
        candidate.is_absolute()
        or raw.endswith(".tar.gz")
        or ("/" in raw)
        or ("\\" in raw)
    )
    if looks_like_path:
        probes = [candidate]
        if not candidate.is_absolute():
            probes.extend(
                [
                    paths.root / candidate,
                    paths.releases_dir / candidate,
                    paths.releases_dir / candidate.name,
                ]
            )
        for probe in probes:
            if is_complete_archive(probe):
                return probe
    return archive_for_sha(paths.releases_dir, raw)


def apply_now(
    paths: UpdaterPaths | None = None,
    *,
    target: str | None = None,
    service: str | None = None,
    run: Runner | None = None,
    sleep: SleepFn = time.sleep,
    get_json=None,
    download=None,
) -> int:
    """Manual path: apply a named local/GitHub package, or GitHub latest.

    ``target`` is a SHA, ``club-…`` tag, or path to an already-uploaded
    ``club-*.tar.gz``. Empty ``target`` keeps the old “download latest” behaviour.
    """
    from django.conf import settings as dj_settings

    paths = paths or UpdaterPaths.from_root(Path(dj_settings.BASE_DIR))
    paths.ensure_dirs()
    service = service or os.environ.get("SERVICE_NAME", "club")
    policy = load_policy()
    token = github_token()
    repo = github_repo()
    want = (target or "").strip() or None
    if want:
        try:
            archive = resolve_rollback_archive(
                paths,
                want,
                token,
                repo,
                get_json=get_json,
                download=download,
                sleep=sleep,
            )
        except UpdaterError:
            log.exception("could not locate package %s", want)
            return 1
        if archive is None:
            return 1
        sha = archive_sha(archive)
        applied = read_applied_sha(paths)
        if sha and sha == applied:
            log.info("already on %s", applied)
            return 0
        try:
            with update_lock(paths.lock_file, blocking=True):
                apply_release(
                    paths,
                    archive,
                    policy,
                    run=run,
                    sleep=sleep,
                    respect_window=False,
                    service=service,
                )
        except ApplyInterrupted as exc:
            log.warning("--apply-now interrupted (%s)", exc.action)
            return 130
        except Exception:
            log.exception("--apply-now failed")
            return 1
        return 0

    remote = None
    if token:
        try:
            remote = poll_and_download(
                paths,
                token,
                repo,
                get_json=get_json,
                download=download,
                sleep=sleep,
            )
        except UpdaterError:
            log.exception("download before --apply-now failed")
    archive = pending_archive(paths, remote_sha=remote.sha if remote else None)
    if archive is None:
        applied = read_applied_sha(paths)
        if remote is not None and remote.sha == applied:
            log.info("already on %s", applied)
            return 0
        log.error("nothing to apply (no complete pending package on disk)")
        return 1
    try:
        with update_lock(paths.lock_file, blocking=True):
            apply_release(
                paths,
                archive,
                policy,
                run=run,
                sleep=sleep,
                respect_window=False,
                service=service,
            )
    except ApplyInterrupted as exc:
        log.warning("--apply-now interrupted (%s)", exc.action)
        return 130
    except Exception:
        log.exception("--apply-now failed")
        return 1
    return 0


def _remote_matches(remote: RemoteRelease, want: str) -> bool:
    return remote.sha == want or remote.sha.startswith(want)


def resolve_rollback_archive(
    paths: UpdaterPaths,
    target: str | None,
    token: str,
    repo: str,
    *,
    get_json: Callable[[str, str], Any] | None = None,
    download: Callable[..., None] | None = None,
    sleep: SleepFn = time.sleep,
) -> Path | None:
    """Locate a previous release tarball: local first, then GitHub."""
    if target:
        archive = local_archive_for_ref(paths, target)
        if archive is not None:
            return archive
        want = normalize_sha(target)
        if not token:
            log.error("no local tarball for %s and UPDATE_GITHUB_TOKEN is empty", want)
            return None
        remote = fetch_release(repo, token, tag=want, get_json=get_json)
        if remote is None:
            log.error("no GitHub release matching %s", want)
            return None
        return download_release(remote, paths, token, download=download, sleep=sleep)

    archive = previous_local_archive(paths)
    if archive is not None:
        return archive
    applied = read_applied_sha(paths)
    if not token:
        log.error("no previous local tarball and UPDATE_GITHUB_TOKEN is empty")
        return None
    found_current = False
    for remote in fetch_releases(repo, token, get_json=get_json):
        if applied and _remote_matches(remote, applied):
            found_current = True
            continue
        if found_current:
            try:
                return download_release(
                    remote, paths, token, download=download, sleep=sleep
                )
            except UpdaterError:
                log.exception("could not download previous release %s", remote.sha)
                continue
    log.error("nothing to roll back to (no older complete release)")
    return None


def rollback_now(
    paths: UpdaterPaths | None = None,
    *,
    target: str | None = None,
    service: str | None = None,
    run: Runner | None = None,
    sleep: SleepFn = time.sleep,
    get_json=None,
    download=None,
) -> int:
    """Apply a previous GitHub release (files + migrate). Does not restore a DB snapshot.

    Failed-apply rollback still restores the pre-apply database snapshot (SQLite
    file or PostgreSQL dump). This path is an intentional pin to an older runtime
    tree; site data stays as-is.
    """
    from django.conf import settings as dj_settings

    paths = paths or UpdaterPaths.from_root(Path(dj_settings.BASE_DIR))
    paths.ensure_dirs()
    service = service or os.environ.get("SERVICE_NAME", "club")
    policy = load_policy()
    token = github_token()
    try:
        archive = resolve_rollback_archive(
            paths,
            target,
            token,
            github_repo(),
            get_json=get_json,
            download=download,
            sleep=sleep,
        )
    except UpdaterError:
        log.exception("rollback download failed")
        return 1
    if archive is None:
        return 1
    sha = archive_sha(archive)
    applied = read_applied_sha(paths)
    if sha and sha == applied:
        log.info("already on %s", applied)
        return 0
    try:
        with update_lock(paths.lock_file, blocking=True):
            apply_release(
                paths,
                archive,
                policy,
                run=run,
                sleep=sleep,
                respect_window=False,
                service=service,
            )
    except ApplyInterrupted as exc:
        log.warning("--rollback interrupted (%s)", exc.action)
        return 130
    except Exception:
        log.exception("--rollback failed")
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _configure_logging()
    _ensure_uv_on_path()
    parser = argparse.ArgumentParser(description="Club GitHub-release updater")
    parser.add_argument(
        "--apply-now",
        nargs="?",
        const="",
        metavar="SHA",
        help=(
            "apply immediately (ignore window). "
            "SHA may be a full hash, 7+ hex prefix, club-… tag, or path to a "
            "club-*.tar.gz already on disk; omit SHA to download+apply GitHub latest"
        ),
    )
    parser.add_argument(
        "--rollback",
        nargs="?",
        const="",
        metavar="SHA",
        help=(
            "apply a previous release immediately (ignore window). "
            "SHA may be a full hash, 7+ hex prefix, or club-… tag; "
            "omit SHA to use the newest local tarball that is not current, "
            "else the GitHub release before the applied one"
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    from django.conf import settings as dj_settings

    paths = UpdaterPaths.from_root(Path(dj_settings.BASE_DIR))
    paths.ensure_dirs()
    service = os.environ.get("SERVICE_NAME", "club")

    if args.apply_now is not None and args.rollback is not None:
        log.error("use either --apply-now or --rollback, not both")
        return 2
    if args.apply_now is not None:
        target = args.apply_now.strip() or None
        return apply_now(paths, target=target, service=service)
    if args.rollback is not None:
        target = args.rollback.strip() or None
        return rollback_now(paths, target=target, service=service)

    log.info("updater loop starting (root=%s)", paths.root)
    while True:
        policy = load_policy()
        interval = max(1, int(policy.update_poll_interval_seconds or 900))
        try:
            poll_tick(paths, policy, service=service, reexec=True)
        except Exception:
            log.exception("updater tick failed")
        time.sleep(interval)
