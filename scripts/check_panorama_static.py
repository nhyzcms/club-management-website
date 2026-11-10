#!/usr/bin/env python3
"""备用防线 3：模拟生产静态收集，校验全景素材可被 collectstatic 完整收集。

线上 404 的根因之一是「本地 runserver 直读 static/，生产却依赖 collectstatic」，
两套路径不一致导致素材没上线。本脚本在本地复现生产路径：

  1. 执行 manage.py collectstatic --noinput（与生产同款命令）；
  2. 断言 staticfiles/panorama/ 下 9 个必需文件全部存在；
  3. 若本次运行前 staticfiles/ 不存在，校验后自动清理，保持仓库干净；
  4. 任一文件缺失 → 非零退出码，CI / 发布前可接入。

用法（仓库根目录）：
  .venv\\Scripts\\python.exe scripts\\check_panorama_static.py
  uv run python scripts/check_panorama_static.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_ROOT = ROOT / "staticfiles"
PANORAMA = ROOT / "static" / "panorama"
REQUIRED = [
    "index.html",
    "marzipano.js",
    *[f"pano_{i}.jpg" for i in range(1, 8)],
]


def pick_python() -> str:
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


def main() -> int:
    py = pick_python()
    print(f"==> python: {py}")

    # 源文件自检（不依赖 collectstatic 即可发现）
    missing_src = [f for f in REQUIRED if not (PANORAMA / f).is_file()]
    if missing_src:
        print(f"FAIL: static/panorama 缺少源文件: {', '.join(missing_src)}")
        return 1
    print(f"==> source ok: static/panorama 9 个文件齐全")

    existed_before = STATIC_ROOT.is_dir()
    cmd = [py, "manage.py", "collectstatic", "--noinput"]
    print("==> running: " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        print("FAIL: collectstatic 执行失败")
        return proc.returncode

    missing = [f for f in REQUIRED if not (STATIC_ROOT / "panorama" / f).is_file()]
    if missing:
        print(f"FAIL: collectstatic 产物缺少全景文件: {', '.join(missing)}")
        print("     （检查 static/panorama 是否在 STATICFILES_DIRS 与打包清单中）")
        return 1

    print("==> OK: staticfiles/panorama 9 个文件全部收集成功，生产路径可用")

    if not existed_before:
        shutil.rmtree(STATIC_ROOT, ignore_errors=True)
        print("==> 已清理本次生成的 staticfiles/（仓库保持干净）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
