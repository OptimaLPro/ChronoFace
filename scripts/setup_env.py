"""
Create or repair the project virtualenv and install dependencies.

Fixes the common Windows failure where NumPy (or other) wheels were built for a
different CPython ABI than the interpreter in .venv (e.g. cp311 wheels under 3.13).

Also rejects broken host installs (missing Lib/), which produce:
  Could not find platform independent libraries <prefix>

Usage (from project root):

    setup.bat
    py -3.11 scripts/setup_env.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MIN_MINOR = 11
MAX_MINOR = 13


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _venv_cfg_version() -> str | None:
    cfg = VENV / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip()
    return None


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(cwd or ROOT))


def _host_stdlib_ok() -> bool:
    """True if this interpreter has a real standard library tree."""
    base = Path(sys.base_prefix)
    return (base / "Lib").is_dir() or (base / "lib").is_dir()


def _check_host_python() -> None:
    if sys.version_info.major != 3 or not (MIN_MINOR <= sys.version_info.minor <= MAX_MINOR):
        raise SystemExit(
            f"Need Python 3.{MIN_MINOR}–3.{MAX_MINOR}, got {sys.version.split()[0]}.\n"
            "Install with:  choco install python311 -y\n"
            "Then re-run:   setup.bat"
        )
    if not _host_stdlib_ok():
        raise SystemExit(
            f"Python at {sys.base_prefix} is incomplete (missing Lib/).\n"
            "Your C:\\Python313 install looks broken — use a full install instead.\n"
            "  choco install python311 -y\n"
            "  or:  py -3.11 scripts/setup_env.py\n"
            "Then re-run setup.bat from a new terminal."
        )


def _imports_ok(python: Path) -> bool:
    probe = (
        "import sys; "
        "import numpy; "
        "import cv2; "
        "import PySide6; "
        "print(sys.version.split()[0], numpy.__version__)"
    )
    try:
        subprocess.check_call(
            [str(python), "-c", probe],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _needs_recreate(python: Path, force: bool) -> bool:
    if force:
        return True
    if not python.is_file():
        return True
    host = f"{sys.version_info.major}.{sys.version_info.minor}"
    cfg = _venv_cfg_version() or ""
    if not cfg.startswith(host):
        print(f"Venv Python mismatch (venv={cfg or '?'}, host={sys.version.split()[0]}). Recreating.")
        return True
    if not _imports_ok(python):
        print("Venv exists but core imports failed (likely ABI mismatch). Recreating.")
        return True
    return False


def setup(*, force: bool = False) -> int:
    _check_host_python()
    if not REQUIREMENTS.is_file():
        raise SystemExit(f"Missing {REQUIREMENTS}")

    python = _venv_python()
    recreated = _needs_recreate(python, force)
    if recreated:
        if VENV.exists():
            print(f"Removing {VENV} ...")
            shutil.rmtree(VENV)
        print(f"Creating venv with {sys.executable} ...")
        _run([sys.executable, "-m", "venv", str(VENV)])
        python = _venv_python()

    _run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    pip_install = [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)]
    if recreated or force:
        # ABI-safe rebuild when the interpreter or broken packages changed.
        pip_install[3:3] = ["--force-reinstall"]
    _run(pip_install)

    print("Verifying imports ...")
    _run(
        [
            str(python),
            "-c",
            "import sys, numpy, cv2, PySide6; "
            "print('OK', sys.version.split()[0], 'numpy', numpy.__version__)",
        ]
    )
    print()
    print("Environment ready. Run the app with:")
    if os.name == "nt":
        print("  run.bat")
        print("  or:  .venv\\Scripts\\python.exe app.py")
    else:
        print("  ./run.sh")
        print("  or:  .venv/bin/python app.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/repair ChronoFace virtualenv")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Always delete and recreate .venv",
    )
    args = parser.parse_args()
    return setup(force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
