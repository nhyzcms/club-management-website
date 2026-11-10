"""Download and assemble frontend/vendor/live2d from jsDelivr + npmmirror.

Same-origin 看板娘 assets: Cubism 2 runtime, stevenjoezhang/live2d-widget@v0.9.2,
and live2d-widget-model-* demo packs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "frontend" / "vendor" / "live2d"
WIDGET_TAG = "v0.9.2"
WIDGET_BASE = f"https://cdn.jsdelivr.net/gh/stevenjoezhang/live2d-widget@{WIDGET_TAG}"
WIDGET_CHUNK_BASE = "https://cdn.jsdelivr.net/gh/stevenjoezhang/live2d-widget@master/dist"
MODEL_REGISTRY = "https://registry.npmmirror.com"
MODEL_VERSION = "1.0.5"

MODEL_PACKAGES = [
    "live2d-widget-model-chitose",
    "live2d-widget-model-epsilon2_1",
    "live2d-widget-model-gf",
    "live2d-widget-model-haru",
    "live2d-widget-model-haruto",
    "live2d-widget-model-hibiki",
    "live2d-widget-model-hijiki",
    "live2d-widget-model-izumi",
    "live2d-widget-model-koharu",
    "live2d-widget-model-miku",
    "live2d-widget-model-ni-j",
    "live2d-widget-model-nico",
    "live2d-widget-model-nietzsche",
    "live2d-widget-model-nipsilon",
    "live2d-widget-model-nito",
    "live2d-widget-model-shizuku",
    "live2d-widget-model-tororo",
    "live2d-widget-model-tsumiki",
    "live2d-widget-model-unitychan",
    "live2d-widget-model-wanko",
    "live2d-widget-model-z16",
]

WIDGET_FILES = [
    "waifu.css",
    "waifu-tips.js",
    "waifu-tips.json",
    "autoload.js",
    "LICENSE",
]
WIDGET_CHUNK_FILES = ["chunk/index.js", "chunk/index2.js"]

UA = {"User-Agent": "nanhui-backend-live2d-vendor/1.0"}


def download(url: str, dest: Path, retries: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    curl = shutil.which("curl")
    for attempt in range(1, retries + 1):
        try:
            if curl:
                result = subprocess.run(
                    [
                        curl,
                        "-fsSL",
                        "--connect-timeout",
                        "20",
                        "--max-time",
                        "120",
                        "-A",
                        UA["User-Agent"],
                        "-o",
                        str(dest),
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or f"curl exit {result.returncode}")
            else:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    dest.write_bytes(resp.read())
            if dest.stat().st_size < 1:
                raise RuntimeError(f"empty download: {url}")
            return
        except Exception as err:  # noqa: BLE001 — retry then raise
            last_err = err
            print(f"  retry {attempt}/{retries} {url}: {err}")
    raise SystemExit(f"download failed {url}: {last_err}")


def patch_autoload(text: str) -> str:
    text = text.replace(
        'const live2d_path = "https://fastly.jsdelivr.net/npm/live2d-widgets@0/";',
        'const live2d_path = "/static/live2d/widget/";',
    )
    text = text.replace(
        'loadExternalResource(live2d_path + "live2d.min.js", "js"),',
        'loadExternalResource("/static/live2d/runtime/live2d.min.js", "js"),',
    )
    old = 'cdnPath: "https://fastly.jsdelivr.net/gh/fghrsh/live2d_api/",'
    new = (
        "// cdnPath omitted: Stream C loads models from /static/live2d/catalog.json.\n"
        "			// Stock switch-model expects cdnPath + model_list.json (fghrsh layout)."
    )
    if old not in text:
        raise SystemExit("autoload.js cdnPath pattern not found; refuse to vendor an unpatched CDN entry")
    text = text.replace(old, new)
    text = text.replace(
        "https://fastly.jsdelivr.net/npm/live2d-widgets@1.0.1/dist/autoload.js",
        "https://github.com/stevenjoezhang/live2d-widget",
    )
    if "jsdelivr.net" in text or "live2d.fghrsh.net" in text.replace("//apiPath", ""):
        # commented apiPath is fine; live loads must not remain
        live = "\n".join(
            line
            for line in text.splitlines()
            if not line.strip().startswith("//") and not line.strip().startswith("console.error")
        )
        if "jsdelivr.net" in live or "live2d.fghrsh.net" in live:
            raise SystemExit("patched autoload.js still loads from CDN; abort")
    return text


GPL2_NOTICE = """GNU GENERAL PUBLIC LICENSE
Version 2, June 1991

This demo model pack is redistributed from
https://github.com/xiazeyu/live2d-widget-models
under GPL-2.0. See that repository for the full license text.
"""


def collect_model_jsons(assets_dir: Path) -> list[Path]:
    return sorted(p for p in assets_dir.rglob("*.model.json") if p.is_file())


def collect_all_model_entries() -> list[dict]:
    """Include locally supplied Cubism 2/3+ models in the generated catalog."""
    models_dir = VENDOR / "models"
    entries: list[dict] = []
    for model_json in sorted(models_dir.rglob("*")):
        if not model_json.is_file() or not (
            model_json.name.endswith(".model.json")
            or model_json.name.endswith(".model3.json")
        ):
            continue
        rel = model_json.relative_to(VENDOR).as_posix()
        model_id = model_json.name.removesuffix(".model3.json").removesuffix(".model.json")
        entries.append({"id": model_id, "name": model_id, "entry": rel})
    return entries


def vendor_widget() -> None:
    runtime = VENDOR / "runtime"
    widget = VENDOR / "widget"
    runtime.mkdir(parents=True, exist_ok=True)
    widget.mkdir(parents=True, exist_ok=True)

    runtime_js = runtime / "live2d.min.js"
    if runtime_js.is_file() and runtime_js.stat().st_size > 50_000:
        print("Cubism 2 runtime already present; skip download")
    else:
        print("Downloading Cubism 2 runtime...")
        download(f"{WIDGET_BASE}/live2d.min.js", runtime_js)
    (runtime / "LICENSE.txt").write_text(
        "Cubism 2 Live2D runtime (live2d.min.js) redistributed from\n"
        f"https://github.com/stevenjoezhang/live2d-widget (tag {WIDGET_TAG}).\n\n"
        "Live2D Cubism SDK is proprietary software of Live2D Inc.\n"
        "See https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html\n"
        "and the header comments inside live2d.min.js.\n",
        encoding="utf-8",
    )

    print("Downloading live2d-widget files...")
    optional = {"README.md", "README.en.md"}
    upstream_path = widget / "autoload.upstream.js"
    if upstream_path.is_file() and (widget / "waifu.css").is_file():
        print("  widget files already present; skip download")
        upstream = upstream_path.read_text(encoding="utf-8")
    else:
        for name in WIDGET_FILES:
            dest = widget / name
            url = f"{WIDGET_BASE}/{name}"
            try:
                download(url, dest)
                print(f"  {name} ({dest.stat().st_size} bytes)")
            except SystemExit:
                if name in optional:
                    print(f"  skip optional {name}")
                    continue
                raise
        upstream = (widget / "autoload.js").read_text(encoding="utf-8")
        upstream_path.write_text(upstream, encoding="utf-8")

    for name in WIDGET_CHUNK_FILES:
        dest = widget / name
        if dest.is_file() and dest.stat().st_size > 1_000:
            print(f"  {name} already present; skip download")
        else:
            download(f"{WIDGET_CHUNK_BASE}/{name}", dest)
            print(f"  {name} ({dest.stat().st_size} bytes)")

    patched = patch_autoload(upstream)
    (widget / "autoload.js").write_text(patched, encoding="utf-8")
    (widget / "README.vendor.md").write_text(
        f"Vendored from https://github.com/stevenjoezhang/live2d-widget tag {WIDGET_TAG} (GPL-3.0).\n"
        "autoload.js is patched to load CSS/JS/runtime from /static/live2d/ (same origin).\n"
        "Original autoload.js is kept as autoload.upstream.js.\n",
        encoding="utf-8",
    )


def vendor_models() -> list[dict]:
    models_dir = VENDOR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    catalog: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for pkg in MODEL_PACKAGES:
            tgz = tmp_path / f"{pkg}.tgz"
            url = f"{MODEL_REGISTRY}/{pkg}/-/{pkg}-{MODEL_VERSION}.tgz"
            print(f"Downloading {pkg}@{MODEL_VERSION}...")
            dest_probe = models_dir / pkg.removeprefix("live2d-widget-model-")
            if dest_probe.is_dir() and any(dest_probe.rglob("*.model.json")):
                print(f"  skip existing {dest_probe.name}")
                jsons = collect_model_jsons(dest_probe)
                slug = dest_probe.name
                for model_json in jsons:
                    stem = model_json.name.removesuffix(".model.json")
                    model_id = slug if len(jsons) == 1 else stem
                    rel = model_json.relative_to(dest_probe).as_posix()
                    catalog.append(
                        {
                            "id": model_id,
                            "name": model_id,
                            "entry": f"models/{slug}/{rel}",
                        }
                    )
                continue
            download(url, tgz)
            extract_to = tmp_path / pkg
            extract_to.mkdir()
            with tarfile.open(tgz, "r:gz") as tar:
                tar.extractall(extract_to, filter="data")
            pkg_root = extract_to / "package"
            assets = pkg_root / "assets"
            search_root = assets if assets.is_dir() else pkg_root
            jsons = collect_model_jsons(search_root)
            if not jsons:
                listing = "\n".join(str(p.relative_to(extract_to)) for p in extract_to.rglob("*") if p.is_file())
                raise SystemExit(f"{pkg} has no *.model.json. Files:\n{listing}")
            slug = pkg.removeprefix("live2d-widget-model-")
            if len(jsons) == 1:
                dest = models_dir / slug
                if dest.exists():
                    shutil.rmtree(dest)
                copied_from = search_root if assets.is_dir() else jsons[0].parent
                shutil.copytree(copied_from, dest)
                (dest / "LICENSE").write_text(GPL2_NOTICE, encoding="utf-8")
                (dest / "README.md").write_text(
                    f"Demo Cubism 2 model pack `{pkg}@{MODEL_VERSION}` from\n"
                    "https://github.com/xiazeyu/live2d-widget-models (GPL-2.0).\n"
                    "Not club-owned 看板娘 IP; replaceable as a directory.\n",
                    encoding="utf-8",
                )
                rel = jsons[0].relative_to(copied_from).as_posix()
                catalog.append({"id": slug, "name": slug, "entry": f"models/{slug}/{rel}"})
            else:
                parents = {model_json.parent for model_json in jsons}
                dest = models_dir / slug
                if dest.exists():
                    shutil.rmtree(dest)
                if len(parents) == 1:
                    shutil.copytree(next(iter(parents)), dest)
                    copied_from = next(iter(parents))
                    (dest / "LICENSE").write_text(GPL2_NOTICE, encoding="utf-8")
                    (dest / "README.md").write_text(
                        f"Demo Cubism 2 model pack `{pkg}@{MODEL_VERSION}` from\n"
                        "https://github.com/xiazeyu/live2d-widget-models (GPL-2.0).\n",
                        encoding="utf-8",
                    )
                    for model_json in jsons:
                        stem = model_json.name.removesuffix(".model.json")
                        rel = model_json.relative_to(copied_from).as_posix()
                        catalog.append(
                            {
                                "id": stem,
                                "name": stem,
                                "entry": f"models/{slug}/{rel}",
                            }
                        )
                else:
                    for model_json in jsons:
                        parent = model_json.parent
                        stem = model_json.name.removesuffix(".model.json")
                        model_id = f"{slug}-{stem}"
                        sub = models_dir / model_id
                        if sub.exists():
                            shutil.rmtree(sub)
                        shutil.copytree(parent, sub)
                        (sub / "LICENSE").write_text(GPL2_NOTICE, encoding="utf-8")
                        (sub / "README.md").write_text(
                            f"Demo Cubism 2 model pack `{pkg}@{MODEL_VERSION}` ({model_json.name})\n"
                            "from https://github.com/xiazeyu/live2d-widget-models (GPL-2.0).\n",
                            encoding="utf-8",
                        )
                        catalog.append(
                            {
                                "id": model_id,
                                "name": model_id,
                                "entry": f"models/{model_id}/{model_json.name}",
                            }
                        )
    return catalog


def main() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    vendor_widget()
    catalog_models = vendor_models()
    known_entries = {model["entry"] for model in catalog_models}
    catalog_models.extend(
        model
        for model in collect_all_model_entries()
        if model["entry"] not in known_entries
    )
    catalog_models.sort(key=lambda m: (0 if m["id"] == "hijiki" else 1, m["id"]))
    (VENDOR / "catalog.json").write_text(
        json.dumps({"version": 1, "models": catalog_models}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    (VENDOR / "LICENSE.models").write_text(GPL2_NOTICE, encoding="utf-8")
    (VENDOR / "README.md").write_text(
        "\n".join(
            [
                "# 看板娘 Live2D vendor tree",
                "",
                "Same-origin static assets for the site-wide 看板娘 overlay (Cubism 2 blog widget).",
                "Webpack copies this directory to `frontend/dist/live2d/` (URL prefix `/static/live2d/`).",
                "",
                "## Layout",
                "",
                "- `runtime/live2d.min.js` — Cubism 2 runtime",
                "- `widget/waifu.css`, `widget/waifu-tips.js`, `widget/waifu-tips.json`",
                "- `widget/autoload.js` — patched to `/static/live2d/` (no CDN at runtime)",
                "- `models/<id>/` — live2d-widget-model-* demo packs",
                "- `catalog.json` — Stream C fetches this; `entry` is relative to `/static/live2d/`",
                "",
                "## Licenses",
                "",
                "- Widget JS/CSS: GPL-3.0 (`widget/LICENSE`)",
                "- Demo models: GPL-2.0 (`models/<id>/LICENSE`)",
                "- Cubism 2 runtime: Live2D Inc. proprietary (`runtime/LICENSE.txt`)",
                "",
                "Demo faces, not club-owned 看板娘 IP. Replacing models is a directory swap.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {VENDOR} with {len(catalog_models)} catalog models")
    print("Default:", catalog_models[0])


if __name__ == "__main__":
    main()
