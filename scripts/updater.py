#!/usr/bin/env python
"""Long-running GitHub Release updater.

Bootstraps Django from the repo root, then hands off to ``common.updater``.
Production: spawned by start.sh next to Gunicorn (same systemd cgroup).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap() -> None:
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def main() -> int:
    _bootstrap()
    from common.updater import main as updater_main

    return updater_main()


if __name__ == "__main__":
    raise SystemExit(main())
