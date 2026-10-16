"""Updater window/cutoff logic and unpack/rollback helpers (no GitHub)."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import sqlite3
import tarfile
import tempfile
import urllib.error
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from common.models import SiteSettings
from common.policy import SitePolicy, get_policy
from common.updater import (
    ApplyError,
    ApplyInterrupted,
    CommandError,
    RemoteRelease,
    SPAWNED_ENV,
    SIGHUP,
    SYNC_EXCLUDES,
    UpdaterError,
    UpdaterPaths,
    WindowClosed,
    apply_now,
    apply_release,
    archive_for_sha,
    archive_sha,
    before_apply_cutoff,
    can_start_apply,
    database_kind,
    db_snapshot_name,
    decide_interrupt,
    download_release,
    fetch_release,
    github_download,
    in_apply_window,
    is_complete_archive,
    load_policy,
    normalize_sha,
    parse_release_assets,
    parse_sha256_sidecar,
    pending_archive,
    pg_dump_command,
    pg_restore_command,
    poll_tick,
    postgres_env,
    previous_local_archive,
    prune_db_backups,
    prune_keep_newest,
    prune_releases,
    release_tag,
    retry_delay,
    restore_sqlite,
    rollback_now,
    sync_tree,
    unpack_archive,
    verify_archive_checksum,
    _format_bytes,
    _format_progress,
    _is_retryable,
)


def _shanghai():
    try:
        return ZoneInfo("Asia/Shanghai")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=8))


def _policy(**kwargs) -> SitePolicy:
    return replace(SitePolicy.defaults(), **kwargs)


def _at(hour, minute=0, *, tz=None):
    tz = tz or _shanghai()
    return datetime(2026, 6, 15, hour, minute, tzinfo=tz)


class WindowLogicTest(SimpleTestCase):
    def test_default_window_bounds(self):
        p = _policy()
        self.assertFalse(in_apply_window(_at(0, 59), p))
        self.assertTrue(in_apply_window(_at(1, 0), p))
        self.assertTrue(in_apply_window(_at(2, 59), p))
        self.assertFalse(in_apply_window(_at(3, 0), p))

    def test_cutoff_blocks_start_but_window_still_open(self):
        p = _policy()
        self.assertTrue(in_apply_window(_at(2, 30), p))
        self.assertFalse(before_apply_cutoff(_at(2, 30), p))
        self.assertTrue(before_apply_cutoff(_at(2, 29), p))
        self.assertTrue(can_start_apply(_at(1, 0), p))
        self.assertFalse(can_start_apply(_at(2, 30), p))

    def test_disabled_blocks_start_even_inside_window(self):
        p = _policy(auto_update_enabled=False)
        self.assertTrue(in_apply_window(_at(1, 30), p))
        self.assertFalse(can_start_apply(_at(1, 30), p))

    def test_uses_policy_timezone_not_naive_clock(self):
        p = _policy(update_timezone="Asia/Shanghai")
        # 2026-06-14 17:00 UTC == 2026-06-15 01:00 CST
        utc = datetime(2026, 6, 14, 17, 0, tzinfo=timezone.utc)
        self.assertTrue(in_apply_window(utc, p))
        self.assertTrue(can_start_apply(utc, p))
        utc_before = datetime(2026, 6, 14, 16, 59, tzinfo=timezone.utc)
        self.assertFalse(in_apply_window(utc_before, p))

    def test_overnight_window_and_cutoff(self):
        p = _policy(
            update_window_start_hour=22,
            update_window_end_hour=2,
            update_apply_cutoff_minutes_before_end=30,
        )
        self.assertFalse(in_apply_window(_at(21, 59), p))
        self.assertTrue(in_apply_window(_at(22, 0), p))
        self.assertTrue(in_apply_window(_at(1, 0), p))
        self.assertFalse(in_apply_window(_at(2, 0), p))
        self.assertTrue(before_apply_cutoff(_at(1, 29), p))
        self.assertFalse(before_apply_cutoff(_at(1, 30), p))

    def test_empty_window_when_start_equals_end(self):
        p = _policy(update_window_start_hour=3, update_window_end_hour=3)
        self.assertFalse(in_apply_window(_at(3, 0), p))
        self.assertFalse(can_start_apply(_at(1, 0), p))

    def test_cutoff_longer_than_window_never_starts(self):
        p = _policy(update_apply_cutoff_minutes_before_end=180)
        self.assertTrue(in_apply_window(_at(1, 0), p))
        self.assertFalse(before_apply_cutoff(_at(1, 0), p))


class ArchiveNameTest(SimpleTestCase):
    def test_sha_from_filename(self):
        sha = "abc123def456"
        self.assertEqual(archive_sha(Path(f"club-{sha}.tar.gz")), sha)

    def test_part_is_never_complete(self):
        part = Path("club-abc123def456.tar.gz.part")
        self.assertIsNone(archive_sha(part))
        self.assertFalse(is_complete_archive(part))

    def test_sidecar_parse_and_verify(self):
        payload = b"hello-release"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "club-deadbeef.tar.gz"
            archive.write_bytes(payload)
            sidecar = Path(str(archive) + ".sha256")
            sidecar.write_text(f"{digest}  club-deadbeef.tar.gz\n", encoding="utf-8")
            self.assertEqual(parse_sha256_sidecar(sidecar.read_text(encoding="utf-8")), digest)
            verify_archive_checksum(archive, sidecar)
            sidecar.write_text("0" * 64 + "  club-deadbeef.tar.gz\n", encoding="utf-8")
            with self.assertRaises(ApplyError):
                verify_archive_checksum(archive, sidecar)


class UnpackExcludeRollbackTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.paths = UpdaterPaths.from_root(self.root)
        self.paths.ensure_dirs()

    def _tarball(self, sha: str, files: dict[str, bytes]) -> Path:
        archive = self.paths.releases_dir / f"club-{sha}.tar.gz"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        archive.write_bytes(buf.getvalue())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        Path(str(archive) + ".sha256").write_text(
            f"{digest}  {archive.name}\n", encoding="utf-8"
        )
        return archive

    def _seed_live(self):
        (self.root / ".env").write_text("SECRET=keep-me\n", encoding="utf-8")
        (self.root / "app.py").write_text("old\n", encoding="utf-8")
        (self.root / "media").mkdir()
        (self.root / "media" / "photo.jpg").write_text("pic", encoding="utf-8")
        (self.root / "private_media").mkdir()
        (self.root / "private_media" / "id.png").write_text("id", encoding="utf-8")
        (self.root / "data").mkdir()
        (self.root / "data" / "media").mkdir()
        (self.root / "data" / "media" / "photo.jpg").write_text("pic", encoding="utf-8")
        (self.root / "run").mkdir(exist_ok=True)
        (self.root / "run" / "gunicorn.sock").write_text("sock", encoding="utf-8")
        (self.root / "backups").mkdir(exist_ok=True)
        (self.root / "backups" / "keep.txt").write_text("bak", encoding="utf-8")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "pyvenv.cfg").write_text("venv", encoding="utf-8")
        conn = sqlite3.connect(self.root / "db.sqlite3")
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('before')")
        conn.commit()
        conn.close()

    def test_unpack_rejects_part(self):
        part = self.paths.releases_dir / "club-aaaaaaa.tar.gz.part"
        part.write_bytes(b"nope")
        with self.assertRaises(ApplyError):
            unpack_archive(part, self.paths.staging_dir)

    def test_apply_and_rollback_ignore_stuck_staging_path(self):
        """A leftover backups/staging the process cannot replace must not block apply."""
        self._seed_live()
        v1 = self._tarball("aaaaaaaaaaaa", {"app.py": b"good\n"})
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"bad\n"})
        unpack_archive(v1, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.paths.applied_file.write_text("aaaaaaaaaaaa\n", encoding="utf-8")

        shutil.rmtree(self.paths.staging_dir)
        self.paths.staging_dir.write_text("stuck leftover\n", encoding="utf-8")

        def run(argv, *, check=True):
            argv = [str(a) for a in argv]
            if "migrate" in argv:
                if check:
                    raise CommandError(argv, 1)
                return 1
            return 0

        with self.assertRaises(CommandError):
            apply_release(
                self.paths,
                v2,
                _policy(),
                run=run,
                sleep=lambda _s: None,
                now_fn=lambda: _at(1, 15),
                respect_window=True,
                drain_seconds=0,
            )

        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "good\n")
        self.assertEqual(
            self.paths.staging_dir.read_text(encoding="utf-8"), "stuck leftover\n"
        )
        self.assertEqual(
            self.paths.applied_file.read_text(encoding="utf-8").strip(), "aaaaaaaaaaaa"
        )
        leftover_temps = [
            p
            for p in self.paths.backups_dir.iterdir()
            if p.is_dir() and p.name.startswith("staging-")
        ]
        self.assertEqual(leftover_temps, [])

    def test_sync_preserves_excludes_and_replaces_code(self):
        self._seed_live()
        src = self.root / "staging-src"
        src.mkdir()
        (src / "app.py").write_text("new\n", encoding="utf-8")
        (src / "added.py").write_text("added\n", encoding="utf-8")
        (src / ".env").write_text("SECRET=from-tarball\n", encoding="utf-8")
        sync_tree(src, self.root)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "new\n")
        self.assertEqual((self.root / "added.py").read_text(encoding="utf-8"), "added\n")
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), "SECRET=keep-me\n")
        self.assertEqual((self.root / "media" / "photo.jpg").read_text(encoding="utf-8"), "pic")
        self.assertEqual(
            (self.root / "private_media" / "id.png").read_text(encoding="utf-8"), "id"
        )
        self.assertEqual(
            (self.root / "data" / "media" / "photo.jpg").read_text(encoding="utf-8"), "pic"
        )
        self.assertTrue((self.root / "run" / "gunicorn.sock").exists())
        self.assertTrue((self.root / "backups" / "keep.txt").exists())
        self.assertTrue((self.root / ".venv" / "pyvenv.cfg").exists())
        self.assertTrue((self.root / "db.sqlite3").exists())

    def test_sync_excludes_constant_covers_live_data(self):
        for name in (
            ".env",
            "db.sqlite3",
            "media",
            "private_media",
            "data",
            "run",
            "backups",
            ".venv",
        ):
            self.assertIn(name, SYNC_EXCLUDES)

    def test_unpack_then_sync_then_rollback_restores_previous_tree_and_db(self):
        self._seed_live()
        v1 = self._tarball("111111111111", {"app.py": b"v1\n", "only_v1.py": b"keep\n"})
        v2 = self._tarball("222222222222", {"app.py": b"v2\n", "only_v2.py": b"new\n"})

        unpack_archive(v1, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "v1\n")

        conn = sqlite3.connect(self.root / "db.sqlite3")
        conn.execute("UPDATE t SET v='after-v1'")
        conn.commit()
        conn.close()
        snapshot = self.paths.backups_dir / "db-test.sqlite3"
        shutil.copy2(self.root / "db.sqlite3", snapshot)

        unpack_archive(v2, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "v2\n")
        self.assertTrue((self.root / "only_v2.py").exists())
        self.assertFalse((self.root / "only_v1.py").exists())

        unpack_archive(v1, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        restore_sqlite(snapshot, self.root / "db.sqlite3")
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "v1\n")
        self.assertTrue((self.root / "only_v1.py").exists())
        self.assertFalse((self.root / "only_v2.py").exists())
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), "SECRET=keep-me\n")
        conn = sqlite3.connect(self.root / "db.sqlite3")
        self.assertEqual(conn.execute("SELECT v FROM t").fetchone()[0], "after-v1")
        conn.close()

    def test_apply_failure_rolls_back_files_and_db(self):
        self._seed_live()
        v1 = self._tarball("aaaaaaaaaaaa", {"app.py": b"good\n"})
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"bad\n"})
        unpack_archive(v1, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.paths.applied_file.write_text("aaaaaaaaaaaa\n", encoding="utf-8")

        calls: list[list[str]] = []

        def run(argv, *, check=True):
            argv = [str(a) for a in argv]
            calls.append(argv)
            if "migrate" in argv:
                if check:
                    raise CommandError(argv, 1)
                return 1
            return 0

        with self.assertRaises(CommandError):
            apply_release(
                self.paths,
                v2,
                _policy(),
                run=run,
                sleep=lambda _s: None,
                now_fn=lambda: _at(1, 15),
                respect_window=True,
                drain_seconds=0,
            )

        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "good\n")
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"), "SECRET=keep-me\n")
        conn = sqlite3.connect(self.root / "db.sqlite3")
        self.assertEqual(conn.execute("SELECT v FROM t").fetchone()[0], "before")
        conn.close()
        self.assertEqual(self.paths.applied_file.read_text(encoding="utf-8").strip(), "aaaaaaaaaaaa")
        self.assertFalse(self.paths.maintenance_flag.exists())
        self.assertTrue(any("migrate" in c for c in calls))
        self.assertTrue(any(c[:4] == ["sudo", "systemctl", "restart", "club"] for c in calls))

    def test_apply_now_ignores_window_and_writes_applied(self):
        self._seed_live()
        v1 = self._tarball("cccccccccccc", {"app.py": b"ok\n"})
        # 14:00 is well outside the 01:00-03:00 window
        apply_release(
            self.paths,
            v1,
            _policy(),
            run=lambda argv, *, check=True: 0,
            sleep=lambda _s: None,
            now_fn=lambda: _at(14, 0),
            respect_window=False,
            drain_seconds=0,
        )
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "ok\n")
        self.assertEqual(self.paths.applied_file.read_text(encoding="utf-8").strip(), "cccccccccccc")
        self.assertFalse(self.paths.maintenance_flag.exists())

    def test_apply_now_named_sha_uses_that_tarball_not_newest(self):
        """`--apply-now SHA` installs that already-uploaded package, not GitHub latest."""
        self._seed_live()
        named = self._tarball("222222222222", {"app.py": b"named\n"})
        decoy = self._tarball("ffffffffffff", {"app.py": b"decoy\n"})
        os.utime(named, (named.stat().st_mtime - 20, named.stat().st_mtime - 20))
        self.paths.applied_file.write_text("111111111111\n", encoding="utf-8")
        with (
            mock.patch("common.updater.load_policy", return_value=_policy()),
            mock.patch("common.updater.github_token", return_value=""),
        ):
            rc = apply_now(
                self.paths,
                target="222222222222",
                run=lambda argv, *, check=True: 0,
                sleep=lambda _s: None,
            )
        self.assertEqual(rc, 0)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "named\n")
        self.assertEqual(
            self.paths.applied_file.read_text(encoding="utf-8").strip(), "222222222222"
        )
        self.assertTrue(decoy.is_file())

    def test_spawned_apply_sighups_parent_instead_of_restart(self):
        self._seed_live()
        v1 = self._tarball("cccccccccccc", {"app.py": b"ok\n"})
        calls: list[list[str]] = []

        def run(argv, *, check=True):
            calls.append([str(a) for a in argv])
            return 0

        with (
            mock.patch.dict(os.environ, {SPAWNED_ENV: "1"}),
            mock.patch("common.updater.os.getppid", return_value=4242),
            mock.patch("common.updater.os.kill") as kill,
        ):
            apply_release(
                self.paths,
                v1,
                _policy(),
                run=run,
                sleep=lambda _s: None,
                now_fn=lambda: _at(1, 15),
                drain_seconds=0,
            )
        kill.assert_called_with(4242, SIGHUP)
        self.assertFalse(
            any(c[:4] == ["sudo", "systemctl", "restart", "club"] for c in calls)
        )

    def test_pending_ignores_part_and_applied_sha(self):
        self._tarball("dddddddddddd", {"app.py": b"x\n"})
        part = self.paths.releases_dir / "club-eeeeeeeeeeee.tar.gz.part"
        part.write_bytes(b"partial")
        self.paths.applied_file.write_text("dddddddddddd\n", encoding="utf-8")
        self.assertIsNone(pending_archive(self.paths, remote_sha="dddddddddddd"))
        self.assertIsNone(pending_archive(self.paths))
        other = self._tarball("ffffffffffff", {"app.py": b"y\n"})
        self.assertEqual(pending_archive(self.paths, remote_sha="ffffffffffff"), other)
        self.assertEqual(pending_archive(self.paths), other)

    def test_pending_does_not_fall_through_to_previous_when_already_on_latest(self):
        """Kept rollback tarballs must not become the next apply target.

        After applying GitHub latest, prune still retains older packages. The
        next tick must not treat the previous tarball as pending, or the
        daemon ping-pongs (503 every ~20s) until the window closes.
        """
        previous = self._tarball("69dd1bdcf436", {"app.py": b"prev\n"})
        latest = self._tarball("2508a65374aa", {"app.py": b"latest\n"})
        os.utime(previous, (previous.stat().st_mtime - 10, previous.stat().st_mtime - 10))
        os.utime(latest, None)
        self.paths.applied_file.write_text("2508a65374aa\n", encoding="utf-8")
        self.assertIsNone(pending_archive(self.paths, remote_sha="2508a65374aa"))
        self.assertIsNone(pending_archive(self.paths))
        self.assertIsNone(pending_archive(self.paths, remote_sha="deadbeefcafebabe"))

    def test_prune_keeps_newest_n(self):
        files = []
        for i, name in enumerate(("a", "b", "c", "d")):
            path = self.paths.releases_dir / f"{name}.tar.gz"
            path.write_text(name, encoding="utf-8")
            stamp = path.stat().st_mtime + i
            os.utime(path, (stamp, stamp))
            files.append(path)
        removed = prune_keep_newest(files, keep=2)
        self.assertEqual(len(removed), 2)
        remaining = {p.name for p in self.paths.releases_dir.glob("*.tar.gz")}
        self.assertEqual(remaining, {"c.tar.gz", "d.tar.gz"})

    def test_prune_releases_removes_sha256_and_part_lock(self):
        old = self._tarball("aaaaaaaaaaaa", {"app.py": b"old\n"})
        new = self._tarball("bbbbbbbbbbbb", {"app.py": b"new\n"})
        os.utime(old, (old.stat().st_mtime - 10, old.stat().st_mtime - 10))
        Path(str(old) + ".part").write_bytes(b"partial")
        Path(str(old) + ".part.lock").write_bytes(b"0")
        Path(str(old) + ".sha256.part").write_text("dead\n", encoding="utf-8")
        removed = prune_releases(self.paths, keep=1)
        self.assertEqual([p.name for p in removed], [old.name])
        self.assertFalse(old.exists())
        self.assertFalse(Path(str(old) + ".sha256").exists())
        self.assertFalse(Path(str(old) + ".part").exists())
        self.assertFalse(Path(str(old) + ".part.lock").exists())
        self.assertFalse(Path(str(old) + ".sha256.part").exists())
        self.assertTrue(new.exists())
        self.assertTrue(Path(str(new) + ".sha256").exists())

    def test_prune_releases_sweeps_orphan_sidecars(self):
        kept = self._tarball("bbbbbbbbbbbb", {"app.py": b"keep\n"})
        orphan_sha = self.paths.releases_dir / "club-aaaaaaaaaaaa.tar.gz.sha256"
        orphan_lock = self.paths.releases_dir / "club-aaaaaaaaaaaa.tar.gz.part.lock"
        orphan_sha.write_text("dead\n", encoding="utf-8")
        orphan_lock.write_bytes(b"0")
        prune_releases(self.paths, keep=5)
        self.assertFalse(orphan_sha.exists())
        self.assertFalse(orphan_lock.exists())
        self.assertTrue(kept.exists())
        self.assertTrue(Path(str(kept) + ".sha256").exists())

    def test_poll_tick_does_not_apply_outside_window(self):
        self._seed_live()
        self._tarball("ffffffffffff", {"app.py": b"new\n"})
        with mock.patch("common.updater.github_token", return_value=""):
            poll_tick(
                self.paths,
                _policy(),
                run=mock.Mock(side_effect=AssertionError("must not apply")),
                sleep=lambda _s: None,
                now_fn=lambda: _at(14, 0),
            )
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "old\n")

    def test_window_close_mid_apply_rolls_back(self):
        self._seed_live()
        v1 = self._tarball("111111111111", {"app.py": b"good\n"})
        v2 = self._tarball("222222222222", {"app.py": b"late\n"})
        unpack_archive(v1, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.paths.applied_file.write_text("111111111111\n", encoding="utf-8")
        ticks = {"n": 0}

        def now():
            ticks["n"] += 1
            # First backup stamp + first window check inside window; then past 03:00.
            if ticks["n"] <= 2:
                return _at(2, 50)
            return _at(3, 1)

        with self.assertRaises(WindowClosed):
            apply_release(
                self.paths,
                v2,
                _policy(),
                run=lambda argv, *, check=True: 0,
                sleep=lambda _s: None,
                now_fn=now,
                respect_window=True,
                drain_seconds=0,
            )
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "good\n")

    def test_rollback_now_pins_named_release_and_keeps_db(self):
        self._seed_live()
        v1 = self._tarball("aaaaaaaaaaaa", {"app.py": b"v1\n"})
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"v2\n"})
        unpack_archive(v2, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.paths.applied_file.write_text("bbbbbbbbbbbb\n", encoding="utf-8")
        conn = sqlite3.connect(self.root / "db.sqlite3")
        conn.execute("UPDATE t SET v='after-v2'")
        conn.commit()
        conn.close()

        with (
            mock.patch("common.updater.load_policy", return_value=_policy()),
            mock.patch("common.updater.github_token", return_value=""),
        ):
            rc = rollback_now(
                self.paths,
                target="aaaaaaaaaaaa",
                run=lambda argv, *, check=True: 0,
                sleep=lambda _s: None,
            )
        self.assertEqual(rc, 0)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "v1\n")
        self.assertEqual(
            self.paths.applied_file.read_text(encoding="utf-8").strip(), "aaaaaaaaaaaa"
        )
        conn = sqlite3.connect(self.root / "db.sqlite3")
        self.assertEqual(conn.execute("SELECT v FROM t").fetchone()[0], "after-v2")
        conn.close()
        self.assertFalse(self.paths.maintenance_flag.exists())
        self.assertTrue(v1.is_file())
        self.assertTrue(v2.is_file())

    def test_rollback_without_target_uses_previous_local(self):
        self._seed_live()
        older = self._tarball("111111111111", {"app.py": b"older\n"})
        newer = self._tarball("222222222222", {"app.py": b"newer\n"})
        os.utime(older, (older.stat().st_mtime - 10, older.stat().st_mtime - 10))
        unpack_archive(newer, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.paths.applied_file.write_text("222222222222\n", encoding="utf-8")

        with (
            mock.patch("common.updater.load_policy", return_value=_policy()),
            mock.patch("common.updater.github_token", return_value=""),
        ):
            rc = rollback_now(
                self.paths,
                target=None,
                run=lambda argv, *, check=True: 0,
                sleep=lambda _s: None,
            )
        self.assertEqual(rc, 0)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "older\n")
        self.assertEqual(
            self.paths.applied_file.read_text(encoding="utf-8").strip(), "111111111111"
        )

    def test_rollback_already_on_target_is_noop(self):
        self._seed_live()
        self._tarball("cccccccccccc", {"app.py": b"same\n"})
        self.paths.applied_file.write_text("cccccccccccc\n", encoding="utf-8")
        with (
            mock.patch("common.updater.load_policy", return_value=_policy()),
            mock.patch("common.updater.github_token", return_value=""),
        ):
            rc = rollback_now(
                self.paths,
                target="cccccccccccc",
                run=mock.Mock(side_effect=AssertionError("must not apply")),
                sleep=lambda _s: None,
            )
        self.assertEqual(rc, 0)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "old\n")

    def test_archive_for_sha_accepts_prefix(self):
        archive = self._tarball("deadbeefcafebabe", {"app.py": b"x\n"})
        self.assertEqual(archive_for_sha(self.paths.releases_dir, "deadbeef"), archive)
        self.assertEqual(
            archive_for_sha(self.paths.releases_dir, "club-deadbeefcafebabe"), archive
        )
        self.assertIsNone(archive_for_sha(self.paths.releases_dir, "dead"))

    def test_previous_local_skips_applied(self):
        a = self._tarball("aaaaaaaaaaaa", {"app.py": b"a\n"})
        b = self._tarball("bbbbbbbbbbbb", {"app.py": b"b\n"})
        os.utime(a, (a.stat().st_mtime - 5, a.stat().st_mtime - 5))
        self.paths.applied_file.write_text("bbbbbbbbbbbb\n", encoding="utf-8")
        self.assertEqual(previous_local_archive(self.paths), a)
        self.assertIsNotNone(b)

    def test_interrupt_before_sync_cancels_and_drops_maintenance(self):
        self._seed_live()
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"v2\n"})

        def check(step, files_changed):
            if step == "backup":
                self.assertFalse(files_changed)
                return "abort_clean"
            return None

        with self.assertRaises(ApplyInterrupted) as caught:
            apply_release(
                self.paths,
                v2,
                _policy(),
                run=lambda argv, *, check=True: 0,
                sleep=lambda _s: None,
                now_fn=lambda: _at(1, 15),
                drain_seconds=0,
                interrupt_check=check,
            )
        self.assertEqual(caught.exception.action, "abort_clean")
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "old\n")
        self.assertFalse(self.paths.maintenance_flag.exists())

    def test_interrupt_after_sync_rolls_back_files_and_db(self):
        self._seed_live()
        v1 = self._tarball("aaaaaaaaaaaa", {"app.py": b"good\n"})
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"bad\n"})
        unpack_archive(v1, self.paths.staging_dir)
        sync_tree(self.paths.staging_dir, self.root)
        self.paths.applied_file.write_text("aaaaaaaaaaaa\n", encoding="utf-8")

        def check(step, files_changed):
            if step == "sync":
                self.assertTrue(files_changed)
                return "rollback"
            return None

        with self.assertRaises(ApplyInterrupted) as caught:
            apply_release(
                self.paths,
                v2,
                _policy(),
                run=lambda argv, *, check=True: 0,
                sleep=lambda _s: None,
                now_fn=lambda: _at(1, 15),
                drain_seconds=0,
                interrupt_check=check,
            )
        self.assertEqual(caught.exception.action, "rollback")
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "good\n")
        conn = sqlite3.connect(self.root / "db.sqlite3")
        self.assertEqual(conn.execute("SELECT v FROM t").fetchone()[0], "before")
        conn.close()
        self.assertEqual(
            self.paths.applied_file.read_text(encoding="utf-8").strip(), "aaaaaaaaaaaa"
        )
        self.assertFalse(self.paths.maintenance_flag.exists())

    def test_interrupt_hold_keeps_maintenance_and_new_files(self):
        self._seed_live()
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"held\n"})

        def check(step, files_changed):
            if step == "sync":
                return "hold"
            return None

        with self.assertRaises(ApplyInterrupted) as caught:
            apply_release(
                self.paths,
                v2,
                _policy(),
                run=mock.Mock(side_effect=AssertionError("must not continue apply")),
                sleep=lambda _s: None,
                now_fn=lambda: _at(1, 15),
                drain_seconds=0,
                interrupt_check=check,
            )
        self.assertEqual(caught.exception.action, "hold")
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "held\n")
        self.assertTrue(self.paths.maintenance_flag.exists())

    def test_interrupt_continue_still_applies(self):
        self._seed_live()
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"v2\n"})
        seen: list[str] = []

        def check(step, files_changed):
            seen.append(step)
            if step in ("backup", "sync"):
                return "continue"
            return None

        sha = apply_release(
            self.paths,
            v2,
            _policy(),
            run=lambda argv, *, check=True: 0,
            sleep=lambda _s: None,
            now_fn=lambda: _at(1, 15),
            drain_seconds=0,
            interrupt_check=check,
        )
        self.assertEqual(sha, "bbbbbbbbbbbb")
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "v2\n")
        self.assertFalse(self.paths.maintenance_flag.exists())
        self.assertIn("backup", seen)
        self.assertIn("sync", seen)


class InterruptDecisionTest(SimpleTestCase):
    def test_no_tty_defaults_to_cancel_before_files_change(self):
        self.assertEqual(
            decide_interrupt(files_changed=False, step="backup", interactive=False),
            "abort_clean",
        )

    def test_no_tty_defaults_to_rollback_after_files_change(self):
        self.assertEqual(
            decide_interrupt(files_changed=True, step="migrate", interactive=False),
            "rollback",
        )

    def test_empty_enter_uses_recommended_choice(self):
        self.assertEqual(
            decide_interrupt(
                files_changed=False, step="drain", interactive=True, reader=lambda _p: ""
            ),
            "abort_clean",
        )
        self.assertEqual(
            decide_interrupt(
                files_changed=True, step="sync", interactive=True, reader=lambda _p: "\n"
            ),
            "rollback",
        )

    def test_interactive_choices(self):
        self.assertEqual(
            decide_interrupt(
                files_changed=True, step="sync", interactive=True, reader=lambda _p: "c"
            ),
            "continue",
        )
        self.assertEqual(
            decide_interrupt(
                files_changed=True, step="sync", interactive=True, reader=lambda _p: "h"
            ),
            "hold",
        )
        self.assertEqual(
            decide_interrupt(
                files_changed=False, step="drain", interactive=True, reader=lambda _p: "继续"
            ),
            "continue",
        )

    def test_eof_and_garbage_use_default(self):
        def boom(_prompt):
            raise EOFError

        self.assertEqual(
            decide_interrupt(
                files_changed=True, step="deps", interactive=True, reader=boom
            ),
            "rollback",
        )
        self.assertEqual(
            decide_interrupt(
                files_changed=False,
                step="drain",
                interactive=True,
                reader=lambda _p: "xyz",
            ),
            "abort_clean",
        )


class GithubParseAndRetryTest(SimpleTestCase):
    def test_release_tag_is_not_bare_hex(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        self.assertEqual(release_tag(sha), f"club-{sha}")
        self.assertEqual(release_tag(f"club-{sha}"), f"club-{sha}")
        self.assertEqual(normalize_sha(f"club-{sha}"), sha)

    def test_fetch_release_falls_back_to_list_for_short_sha(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        payload = {
            "tag_name": f"club-{sha}",
            "assets": [
                {
                    "name": f"club-{sha}.tar.gz",
                    "url": "https://api.github.com/repos/x/y/releases/assets/1",
                },
                {
                    "name": f"club-{sha}.tar.gz.sha256",
                    "url": "https://api.github.com/repos/x/y/releases/assets/2",
                },
            ],
        }

        def get_json(url, token):
            if "/releases/tags/" in url:
                raise UpdaterError("GitHub HTTP 404")
            if "releases?per_page=30" in url:
                return [payload]
            raise AssertionError(url)

        remote = fetch_release("x/y", "tok", tag=sha[:12], get_json=get_json)
        self.assertIsInstance(remote, RemoteRelease)
        self.assertEqual(remote.sha, sha)

    def test_parse_release_assets(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        payload = {
            "tag_name": f"club-{sha}",
            "assets": [
                {
                    "name": f"club-{sha}.tar.gz",
                    "url": "https://api.github.com/repos/x/y/releases/assets/1",
                },
                {
                    "name": f"club-{sha}.tar.gz.sha256",
                    "url": "https://api.github.com/repos/x/y/releases/assets/2",
                },
            ],
        }
        remote = parse_release_assets(payload)
        self.assertIsInstance(remote, RemoteRelease)
        self.assertEqual(remote.sha, sha)
        self.assertTrue(remote.tarball_api_url.endswith("/1"))
        self.assertTrue(remote.checksum_api_url.endswith("/2"))

    def test_parse_skips_nameless_payload(self):
        self.assertIsNone(parse_release_assets({"assets": []}))

    def test_retry_delay_jitter_bounds(self):
        self.assertEqual(retry_delay(0, base=5, cap=300, jitter=lambda: 0.0), 2.5)
        self.assertEqual(retry_delay(0, base=5, cap=300, jitter=lambda: 1.0), 5.0)
        self.assertEqual(retry_delay(10, base=5, cap=300, jitter=lambda: 1.0), 300.0)

    def test_format_progress_includes_percent_and_rate(self):
        self.assertEqual(_format_bytes(512), "512 B")
        self.assertIn("KiB", _format_bytes(2048))
        line = _format_progress("club.tgz.part", 10 * 1024 * 1024, 40 * 1024 * 1024, 1024 * 1024)
        self.assertIn("25%", line)
        self.assertIn("/s", line)

    def test_http_503_is_retryable_404_is_not(self):
        err_503 = urllib.error.HTTPError("http://x", 503, "unavailable", hdrs=None, fp=None)
        err_404 = urllib.error.HTTPError("http://x", 404, "missing", hdrs=None, fp=None)
        self.assertTrue(_is_retryable(err_503))
        self.assertFalse(_is_retryable(err_404))
        self.assertTrue(_is_retryable(urllib.error.URLError("timeout")))

    def test_poll_tick_skips_download_when_disabled(self):
        with tempfile.TemporaryDirectory() as raw:
            paths = UpdaterPaths.from_root(Path(raw))
            paths.ensure_dirs()
            get_json = mock.Mock(side_effect=AssertionError("must not hit GitHub"))
            remote = poll_tick(
                paths,
                _policy(auto_update_enabled=False),
                get_json=get_json,
                download=mock.Mock(),
                sleep=lambda _s: None,
                apply=False,
            )
            self.assertIsNone(remote)
            get_json.assert_not_called()


class LoadPolicyCacheTest(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_load_policy_invalidates_then_rereads(self):
        obj, _ = SiteSettings.objects.get_or_create(pk=1)
        obj.auto_update_enabled = True
        obj.save()
        self.assertTrue(get_policy().auto_update_enabled)
        SiteSettings.objects.filter(pk=1).update(auto_update_enabled=False)
        self.assertTrue(get_policy().auto_update_enabled)
        self.assertFalse(load_policy().auto_update_enabled)


class _FakeHttp:
    def __init__(self, *, status=200, body=b"", headers=None):
        self.status = status
        self.headers = headers or {}
        self._buf = io.BytesIO(body)

    def read(self, n=-1):
        return self._buf.read(n)

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_opener(handler):
    opener = mock.Mock()
    opener.open.side_effect = handler
    return mock.patch("common.updater._opener", return_value=opener)


class GithubDownloadResumeTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name) / "club-deadbeef.tar.gz.part"

    def test_premature_eof_keeps_partial_and_raises(self):
        payload = b"x" * 100

        def open_req(req, timeout=None):
            return _FakeHttp(
                status=200,
                body=payload[:50],
                headers={"Content-Length": "100"},
            )

        with _patch_opener(open_req), self.assertLogs("updater", level="INFO") as cm:
            with self.assertRaises(UpdaterError) as ctx:
                github_download("https://api.github.com/asset", self.dest, "tok")
        self.assertIn("incomplete", str(ctx.exception).lower())
        self.assertEqual(self.dest.read_bytes(), payload[:50])
        self.assertTrue(any("keeping partial for resume" in line for line in cm.output))

    def test_resume_sends_range_and_appends_206(self):
        payload = b"abcdefghij"
        self.dest.write_bytes(payload[:6])
        captured = {}

        def open_req(req, timeout=None):
            captured["range"] = req.get_header("Range")
            return _FakeHttp(
                status=206,
                body=payload[6:],
                headers={
                    "Content-Length": "4",
                    "Content-Range": "bytes 6-9/10",
                },
            )

        with _patch_opener(open_req), self.assertLogs("updater", level="INFO") as cm:
            github_download("https://api.github.com/asset", self.dest, "tok")
        self.assertEqual(captured["range"], "bytes=6-")
        self.assertEqual(self.dest.read_bytes(), payload)
        joined = "\n".join(cm.output)
        self.assertIn("requesting Range: bytes=6-", joined)
        self.assertIn("resume accepted: HTTP 206", joined)
        self.assertIn("resume finished:", joined)

    def test_server_ignoring_range_overwrites_partial(self):
        payload = b"abcdefghij"
        self.dest.write_bytes(b"XXXXXX")

        def open_req(req, timeout=None):
            return _FakeHttp(
                status=200,
                body=payload,
                headers={"Content-Length": "10"},
            )

        with _patch_opener(open_req), self.assertLogs("updater", level="INFO") as cm:
            github_download("https://api.github.com/asset", self.dest, "tok")
        self.assertEqual(self.dest.read_bytes(), payload)
        self.assertTrue(any("resume rejected: HTTP 200" in line for line in cm.output))

    def test_network_error_keeps_partial(self):
        self.dest.write_bytes(b"already")

        def open_req(req, timeout=None):
            raise urllib.error.URLError("connection reset")

        with _patch_opener(open_req), self.assertLogs("updater", level="INFO") as cm:
            with self.assertRaises(UpdaterError):
                github_download("https://api.github.com/asset", self.dest, "tok")
        self.assertEqual(self.dest.read_bytes(), b"already")
        self.assertTrue(any("keeping partial for resume" in line for line in cm.output))

    def test_download_release_resumes_partial_across_retries(self):
        payload = b"complete-archive-bytes"
        digest = hashlib.sha256(payload).hexdigest()
        sidecar = f"{digest}  club-aaaaaaaa.tar.gz\n"
        paths = UpdaterPaths.from_root(Path(self._tmp.name))
        paths.ensure_dirs()
        remote = RemoteRelease(
            sha="aaaaaaaa",
            tarball_name="club-aaaaaaaa.tar.gz",
            tarball_api_url="https://api.github.com/tarball",
            checksum_api_url="https://api.github.com/sidecar",
        )
        tarball_calls = []

        def save(url, dest, token):
            if url.endswith("/sidecar"):
                dest.write_text(sidecar, encoding="utf-8")
                return
            tarball_calls.append(dest.stat().st_size if dest.is_file() else 0)
            if not dest.is_file() or dest.stat().st_size == 0:
                dest.write_bytes(payload[:10])
                raise urllib.error.URLError("reset after 10 bytes")
            with dest.open("ab") as fh:
                fh.write(payload[10:])

        dest = download_release(remote, paths, "tok", download=save, sleep=lambda _s: None)
        self.assertEqual(dest.read_bytes(), payload)
        self.assertEqual(tarball_calls, [0, 10])
        self.assertFalse(Path(str(dest) + ".part").exists())


class DownloadLockTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = UpdaterPaths.from_root(Path(self._tmp.name))
        self.paths.ensure_dirs()
        self.payload = b"complete-archive-bytes"
        digest = hashlib.sha256(self.payload).hexdigest()
        self.sidecar = f"{digest}  club-aaaaaaaa.tar.gz\n"
        self.remote = RemoteRelease(
            sha="aaaaaaaa",
            tarball_name="club-aaaaaaaa.tar.gz",
            tarball_api_url="https://api.github.com/tarball",
            checksum_api_url="https://api.github.com/sidecar",
        )
        self.dest = self.paths.releases_dir / self.remote.tarball_name
        self.part_lock = Path(str(self.dest) + ".part.lock")

    def _save(self, url, dest, token):
        if url.endswith("/sidecar"):
            dest.write_text(self.sidecar, encoding="utf-8")
            return
        dest.write_bytes(self.payload)

    def test_skips_download_when_complete_archive_already_present(self):
        self.dest.write_bytes(self.payload)
        Path(str(self.dest) + ".sha256").write_text(self.sidecar, encoding="utf-8")

        def save(url, dest, token):
            raise AssertionError("must not re-download a verified archive")

        dest = download_release(
            self.remote, self.paths, "tok", download=save, sleep=lambda _s: None
        )
        self.assertEqual(dest.read_bytes(), self.payload)

    def test_waits_on_part_lock_then_reuses_peer_archive(self):
        """Daemon and --apply-now share backups/releases/*.part; the waiter must not write."""

        def save(url, dest, token):
            raise AssertionError("waiter must reuse the archive the peer just finished")

        @contextmanager
        def fake_lock(lock_path, *, blocking=True):
            self.assertEqual(lock_path, self.part_lock)
            self.dest.write_bytes(self.payload)
            Path(str(self.dest) + ".sha256").write_text(self.sidecar, encoding="utf-8")
            yield

        with mock.patch("common.updater.update_lock", fake_lock):
            dest = download_release(
                self.remote, self.paths, "tok", download=save, sleep=lambda _s: None
            )
        self.assertEqual(dest, self.dest)
        self.assertEqual(dest.read_bytes(), self.payload)

    def test_logs_and_blocks_when_part_lock_is_held(self):
        calls: list[bool] = []

        @contextmanager
        def fake_lock(lock_path, *, blocking=True):
            self.assertEqual(lock_path, self.part_lock)
            calls.append(blocking)
            if not blocking:
                raise BlockingIOError("update lock held")
            yield

        with mock.patch("common.updater.update_lock", fake_lock):
            with self.assertLogs("updater", level="INFO") as cm:
                dest = download_release(
                    self.remote,
                    self.paths,
                    "tok",
                    download=self._save,
                    sleep=lambda _s: None,
                )
        self.assertEqual(calls, [False, True])
        self.assertTrue(
            any("waiting for another process" in line for line in cm.output)
        )
        self.assertEqual(dest.read_bytes(), self.payload)


class PostgresSnapshotTest(SimpleTestCase):
    """PostgreSQL 快照便道：database_kind 分流、pg_dump/psql 命令、失败回滚走 psql。"""

    PG = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "club",
        "USER": "club",
        "PASSWORD": "pw",
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.paths = UpdaterPaths.from_root(self.root)
        self.paths.ensure_dirs()
        self.paths.backups_dir.mkdir(parents=True, exist_ok=True)

    def _tarball(self, sha: str, files: dict[str, bytes]) -> Path:
        archive = self.paths.releases_dir / f"club-{sha}.tar.gz"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        archive.write_bytes(buf.getvalue())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        Path(str(archive) + ".sha256").write_text(
            f"{digest}  {archive.name}\n", encoding="utf-8"
        )
        return archive

    def test_database_kind_and_snapshot_name(self):
        with override_settings(DATABASES={"default": self.PG}):
            self.assertEqual(database_kind(), "postgres")
            self.assertEqual(
                db_snapshot_name("20261010-000000"), "db-20261010-000000.pg.sql"
            )
        self.assertEqual(database_kind(), "sqlite")
        self.assertEqual(db_snapshot_name("x"), "db-x.sqlite3")

    def test_pg_commands_built_from_settings(self):
        with (
            override_settings(DATABASES={"default": self.PG}),
            mock.patch(
                "common.updater.find_pg_tool", side_effect=lambda n: f"/usr/bin/{n}"
            ),
        ):
            dump = pg_dump_command(Path("/tmp/snap.sql"))
            restore = pg_restore_command(Path("/tmp/snap.sql"))
            env = postgres_env()
        self.assertEqual(dump[0], "/usr/bin/pg_dump")
        for flag in ("--clean", "--if-exists", "--no-owner", "--no-acl"):
            self.assertIn(flag, dump)
        self.assertEqual(dump[-2:], ["-f", "/tmp/snap.sql"])
        self.assertEqual(restore[0], "/usr/bin/psql")
        self.assertIn("ON_ERROR_STOP=1", restore)
        self.assertEqual(restore[-2:], ["-f", "/tmp/snap.sql"])
        self.assertEqual(env["PGPASSWORD"], "pw")

    def test_apply_failure_on_postgres_restores_via_psql(self):
        (self.root / "app.py").write_text("old\n", encoding="utf-8")
        self.paths.applied_file.write_text("aaaaaaaaaaaa\n", encoding="utf-8")
        v2 = self._tarball("bbbbbbbbbbbb", {"app.py": b"bad\n"})
        snapshot = self.paths.backups_dir / "db-20260615-011500.pg.sql"
        calls: list[list[str]] = []

        def run(argv, *, check=True, env=None):
            argv = [str(a) for a in argv]
            calls.append(argv)
            if Path(argv[0]).name == "pg_dump":
                Path(argv[argv.index("-f") + 1]).write_text(
                    "-- dump\n", encoding="utf-8"
                )
                return 0
            if "migrate" in argv:
                raise CommandError(argv, 1)
            return 0

        with (
            override_settings(DATABASES={"default": self.PG}),
            mock.patch(
                "common.updater.find_pg_tool", side_effect=lambda n: f"/usr/bin/{n}"
            ),
        ):
            with self.assertRaises(CommandError):
                apply_release(
                    self.paths,
                    v2,
                    _policy(),
                    run=run,
                    sleep=lambda _s: None,
                    now_fn=lambda: _at(1, 15),
                    drain_seconds=0,
                )

        self.assertTrue(snapshot.is_file())
        psql_calls = [c for c in calls if Path(c[0]).name == "psql"]
        self.assertEqual(len(psql_calls), 1)
        self.assertIn(str(snapshot), psql_calls[0])
        self.assertFalse(self.paths.maintenance_flag.exists())

    def test_prune_db_backups_keeps_newest_across_kinds(self):
        old = self.paths.backups_dir / "db-20261001-000000.sqlite3"
        mid = self.paths.backups_dir / "db-20261005-000000.pg.sql"
        new = self.paths.backups_dir / "db-20261010-000000.pg.sql"
        for i, path in enumerate((old, mid, new)):
            path.write_text("x", encoding="utf-8")
            stamp = 1000 + i
            os.utime(path, (stamp, stamp))
        removed = prune_db_backups(self.paths, keep=2)
        self.assertEqual([p.name for p in removed], [old.name])
        self.assertFalse(old.exists())
        self.assertTrue(mid.exists())
        self.assertTrue(new.exists())
