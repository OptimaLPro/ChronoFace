"""Run pip installs into the same interpreter ChronoFace is using."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence


ProgressCallback = Callable[[str], None]


def pip_install(
    packages: Sequence[str],
    *,
    index_url: str | None = None,
    no_build_isolation: bool = False,
    on_progress: ProgressCallback | None = None,
) -> None:
    """
    Install packages with ``python -m pip`` for the running interpreter.

    Raises RuntimeError with combined output when pip fails.
    """
    if not packages:
        return

    cmd = [sys.executable, "-m", "pip", "install", *packages]
    if index_url:
        cmd.extend(["--index-url", index_url])
    if no_build_isolation:
        cmd.append("--no-build-isolation")

    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return

    detail = (completed.stderr or completed.stdout or "").strip()
    raise RuntimeError(
        f"Could not install {' '.join(packages)}.\n\n{detail[-2000:]}"
    )
