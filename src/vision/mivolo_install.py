"""Install optional MiVOLO age-backend dependencies into the current env."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

from src.utils.pip_install import pip_install

ProgressCallback = Callable[[str], None]

_TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu124"
_TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
_MIVOLO_GIT = "git+https://github.com/WildChlamydia/MiVOLO.git"


def _torch_index_url() -> str:
    """Prefer CUDA wheels when an NVIDIA GPU is present; otherwise CPU."""
    if shutil.which("nvidia-smi") is None:
        return _TORCH_CPU_INDEX
    try:
        completed = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _TORCH_CPU_INDEX
    if completed.returncode == 0:
        return _TORCH_CUDA_INDEX
    return _TORCH_CPU_INDEX


def install_mivolo_dependencies(
    *,
    on_progress: ProgressCallback | None = None,
) -> None:
    """
    Install PyTorch, transformers, and the MiVOLO package.

    Steps match the comments in requirements.txt. Raises RuntimeError on failure.
    """
    index = _torch_index_url()
    steps: list[tuple[str, Callable[[], None]]] = [
        (
            "Installing the AI engine (PyTorch)… this can take several minutes",
            lambda: pip_install(
                ["torch", "torchvision"],
                index_url=index,
                on_progress=on_progress,
            ),
        ),
        (
            "Installing supporting libraries…",
            lambda: pip_install(
                ["transformers", "accelerate", "setuptools<81"],
                on_progress=on_progress,
            ),
        ),
        (
            "Installing the age model package (MiVOLO)…",
            lambda: pip_install(
                [_MIVOLO_GIT],
                no_build_isolation=True,
                on_progress=on_progress,
            ),
        ),
    ]

    for label, action in steps:
        if on_progress is not None:
            on_progress(label)
        action()
