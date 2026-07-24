"""Tests for optional dependency install helpers (no real pip)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.utils.pip_install import pip_install
from src.vision.mivolo_install import install_mivolo_dependencies


def test_pip_install_builds_expected_command() -> None:
    completed = MagicMock(returncode=0, stdout="", stderr="")
    with patch("src.utils.pip_install.subprocess.run", return_value=completed) as run:
        with patch("src.utils.pip_install.sys.executable", "/venv/python"):
            pip_install(
                ["torch", "torchvision"],
                index_url="https://download.pytorch.org/whl/cu124",
            )

    run.assert_called_once()
    cmd = run.call_args.args[0]
    assert cmd[:4] == ["/venv/python", "-m", "pip", "install"]
    assert "torch" in cmd
    assert "torchvision" in cmd
    assert "--index-url" in cmd
    assert "https://download.pytorch.org/whl/cu124" in cmd


def test_pip_install_raises_on_failure() -> None:
    completed = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("src.utils.pip_install.subprocess.run", return_value=completed):
        with pytest.raises(RuntimeError, match="Could not install"):
            pip_install(["does-not-exist"])


def test_install_mivolo_dependencies_runs_three_steps() -> None:
    calls: list[tuple] = []

    def fake_pip(packages, *, index_url=None, no_build_isolation=False, on_progress=None):
        calls.append((list(packages), index_url, no_build_isolation))

    with patch("src.vision.mivolo_install.pip_install", side_effect=fake_pip):
        with patch(
            "src.vision.mivolo_install._torch_index_url",
            return_value="https://download.pytorch.org/whl/cpu",
        ):
            messages: list[str] = []
            install_mivolo_dependencies(on_progress=messages.append)

    assert len(calls) == 3
    assert calls[0][0] == ["torch", "torchvision"]
    assert calls[0][1] == "https://download.pytorch.org/whl/cpu"
    assert "transformers" in calls[1][0]
    assert calls[2][2] is True  # no_build_isolation for MiVOLO git install
    assert len(messages) == 3
