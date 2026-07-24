"""
Build a Windows portable folder with PyInstaller.

Usage (from project root, venv active):

    python scripts/build_windows.py

Output:

    dist/ChronoFace/
        ChronoFace.exe
        models/   (YuNet, SFace, age model if present)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "ChronoFace"
BUILD = ROOT / "build" / "pyinstaller"
MODELS = ROOT / "models"
ASSETS = ROOT / "assets"
ICON_ICO = ASSETS / "app_icon.ico"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: pip install pyinstaller")
        return 1

    entry = ROOT / "app.py"
    if not entry.exists():
        print(f"Missing entry point: {entry}")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "ChronoFace",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(BUILD),
        "--paths",
        str(ROOT),
        "--collect-all",
        "PySide6",
        "--collect-all",
        "onnxruntime",
        "--hidden-import",
        "cv2",
        "--hidden-import",
        "PIL",
        "--hidden-import",
        "piexif",
        str(entry),
    ]
    if ICON_ICO.is_file():
        cmd.extend(["--icon", str(ICON_ICO)])
    else:
        print(f"Warning: missing app icon at {ICON_ICO}")

    print("Running:", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=ROOT)
    if completed.returncode != 0:
        return completed.returncode

    app_dir = ROOT / "dist" / "ChronoFace"
    # onedir default name matches --name
    if not app_dir.exists():
        # older/onefile layouts
        print(f"Build finished. Check {ROOT / 'dist'}")
        return 0

    target_models = app_dir / "models"
    target_models.mkdir(parents=True, exist_ok=True)
    copied = 0
    for model in MODELS.glob("*.onnx"):
        shutil.copy2(model, target_models / model.name)
        copied += 1
        print(f"Bundled model: {model.name}")

    target_assets = app_dir / "assets"
    if ASSETS.is_dir():
        if target_assets.exists():
            shutil.rmtree(target_assets)
        shutil.copytree(
            ASSETS,
            target_assets,
            ignore=shutil.ignore_patterns(".gitkeep"),
        )
        print(f"Bundled assets from {ASSETS}")

    readme = app_dir / "README_PORTABLE.txt"
    readme.write_text(
        "ChronoFace — portable Windows build\n\n"
        "1. Run ChronoFace.exe\n"
        "2. All analysis stays on this PC\n"
        "3. Models are in the models\\ folder next to the exe\n"
        f"4. Bundled ONNX models: {copied}\n",
        encoding="utf-8",
    )
    print(f"\nPortable build ready: {app_dir}")
    print("Run ChronoFace.exe from that folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
