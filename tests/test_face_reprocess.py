"""Tests for model-change face reprocess detection."""

from __future__ import annotations

from pathlib import Path

from src.settings.app_settings import AppSettings
from src.vision.model_catalog import ModelPresetId
from src.workers.face_pipeline import (
    project_needs_face_reprocess,
    read_project_model_fingerprint,
    write_project_model_fingerprint,
)


def test_empty_fingerprint_counts_as_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.workers.face_pipeline.project_cache_dir",
        lambda project_id: tmp_path / project_id,
    )
    settings = AppSettings(
        model_preset=ModelPresetId.INSIGHTFACE_BUFFALO_L.value,
        force_reprocess_after_model_change=True,
    )
    needs, previous, current = project_needs_face_reprocess("proj-1", settings)
    assert previous == ""
    assert "buffalo_l" in current
    assert needs is True


def test_matching_fingerprint_skips_reprocess(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.workers.face_pipeline.project_cache_dir",
        lambda project_id: tmp_path / project_id,
    )
    settings = AppSettings(
        model_preset=ModelPresetId.OPENCV_FAST.value,
        force_reprocess_after_model_change=True,
    )
    write_project_model_fingerprint("proj-1", settings.model_fingerprint())
    needs, previous, current = project_needs_face_reprocess("proj-1", settings)
    assert needs is False
    assert previous == current


def test_different_fingerprint_requires_reprocess(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.workers.face_pipeline.project_cache_dir",
        lambda project_id: tmp_path / project_id,
    )
    write_project_model_fingerprint("proj-1", "opencv_fast|det=640")
    settings = AppSettings(
        model_preset=ModelPresetId.INSIGHTFACE_BUFFALO_L.value,
        force_reprocess_after_model_change=True,
    )
    needs, previous, current = project_needs_face_reprocess("proj-1", settings)
    assert needs is True
    assert previous.startswith("opencv_fast")
    assert "buffalo_l" in current
    assert read_project_model_fingerprint("proj-1") == previous
