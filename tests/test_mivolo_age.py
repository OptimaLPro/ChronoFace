"""Tests for optional MiVOLO age backend wiring (no heavy download required)."""

from __future__ import annotations

from src.settings.app_settings import AppSettings
from src.vision.age_backends import AgeBackendId
from src.vision.model_catalog import ModelPresetId
from src.vision.mivolo_age import mivolo_available


def test_fingerprint_includes_age_backend() -> None:
    builtin = AppSettings(
        model_preset=ModelPresetId.OPENCV_FAST.value,
        age_backend=AgeBackendId.BUILTIN.value,
    )
    mivolo = AppSettings(
        model_preset=ModelPresetId.OPENCV_FAST.value,
        age_backend=AgeBackendId.MIVOLO_V2.value,
    )
    assert builtin.model_fingerprint() != mivolo.model_fingerprint()
    assert "age=builtin" in builtin.model_fingerprint()
    assert "age=mivolo_v2" in mivolo.model_fingerprint()


def test_mivolo_available_is_bool() -> None:
    assert isinstance(mivolo_available(), bool)
