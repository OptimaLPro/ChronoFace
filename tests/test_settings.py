"""Tests for app settings and model catalog."""

from __future__ import annotations

from pathlib import Path

from src.settings.app_settings import AppSettings, load_settings, save_settings
from src.vision.age_backends import AgeBackendId, list_age_backends
from src.vision.model_catalog import (
    ModelPresetId,
    get_preset,
    list_presets,
)


def test_presets_have_tradeoff_copy() -> None:
    presets = list_presets()
    assert len(presets) >= 4
    ids = {preset.id for preset in presets}
    assert ModelPresetId.OPENCV_FAST in ids
    assert ModelPresetId.INSIGHTFACE_BUFFALO_L in ids
    recommended = [preset for preset in presets if preset.recommended]
    assert len(recommended) == 1
    assert recommended[0].id == ModelPresetId.INSIGHTFACE_BUFFALO_L
    for preset in presets:
        assert preset.speed
        assert preset.quality
        assert preset.effort
        assert preset.summary
        assert preset.license_note
        assert 0.0 < preset.default_match_threshold < 1.0


def test_age_backends_catalog() -> None:
    backends = list_age_backends()
    ids = {backend.id for backend in backends}
    assert AgeBackendId.BUILTIN in ids
    assert AgeBackendId.MIVOLO_V2 in ids
    assert any(backend.recommended for backend in backends)


def test_settings_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.settings.app_settings.app_data_dir",
        lambda: tmp_path,
    )
    settings = AppSettings(
        model_preset=ModelPresetId.INSIGHTFACE_BUFFALO_S.value,
        age_backend=AgeBackendId.MIVOLO_V2.value,
        match_threshold=0.41,
        low_confidence_threshold=0.33,
        det_size=512,
        show_privacy_banner=False,
    )
    save_settings(settings)
    loaded = load_settings()
    assert loaded.model_preset == ModelPresetId.INSIGHTFACE_BUFFALO_S.value
    assert loaded.age_backend == AgeBackendId.MIVOLO_V2.value
    assert loaded.match_threshold == 0.41
    assert loaded.low_confidence_threshold == 0.33
    assert loaded.det_size == 512
    assert loaded.show_privacy_banner is False
    assert loaded.effective_match_threshold() == 0.41
    assert "buffalo_s" in loaded.model_fingerprint()
    assert "mivolo_v2" in loaded.model_fingerprint()


def test_auto_thresholds_use_preset_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.settings.app_settings.app_data_dir",
        lambda: tmp_path,
    )
    settings = AppSettings(model_preset=ModelPresetId.OPENCV_FAST.value)
    preset = get_preset(ModelPresetId.OPENCV_FAST)
    assert settings.effective_match_threshold() == preset.default_match_threshold
    assert (
        settings.effective_low_confidence_threshold()
        == preset.default_low_confidence_threshold
    )
