"""Persist and load application settings as JSON under the app data dir."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from src.utils.logging import get_logger
from src.utils.paths import app_data_dir
from src.vision.age_backends import (
    AgeBackendId,
    default_age_backend_id,
)
from src.vision.model_catalog import (
    ModelPresetId,
    default_preset_id,
    get_preset,
)

logger = get_logger("settings.app_settings")

SETTINGS_FILENAME = "settings.json"
SETTINGS_VERSION = 1


@dataclass
class AppSettings:
    """Global user preferences (not per-project)."""

    version: int = SETTINGS_VERSION
    model_preset: str = default_preset_id().value
    """Selected :class:`ModelPresetId` value."""

    age_backend: str = default_age_backend_id().value
    """Selected :class:`AgeBackendId` value (builtin or mivolo_v2)."""

    match_threshold: float | None = None
    """If None, use the preset's default match threshold."""

    low_confidence_threshold: float | None = None
    """If None, use the preset's default low-confidence threshold."""

    det_size: int = 640
    """InsightFace detection input size (square). Larger = better small faces, slower."""

    force_reprocess_after_model_change: bool = True
    """When the model preset changes, next analysis re-runs face matching."""

    last_model_fingerprint: str = ""
    """Fingerprint of the model pack that produced current embeddings."""

    show_privacy_banner: bool = True
    log_verbose: bool = False

    def resolved_preset_id(self) -> ModelPresetId:
        try:
            return ModelPresetId(self.model_preset)
        except ValueError:
            return default_preset_id()

    def resolved_age_backend_id(self) -> AgeBackendId:
        try:
            return AgeBackendId(self.age_backend)
        except ValueError:
            return default_age_backend_id()

    def effective_match_threshold(self) -> float:
        if self.match_threshold is not None:
            return float(self.match_threshold)
        return get_preset(self.resolved_preset_id()).default_match_threshold

    def effective_low_confidence_threshold(self) -> float:
        if self.low_confidence_threshold is not None:
            return float(self.low_confidence_threshold)
        return get_preset(self.resolved_preset_id()).default_low_confidence_threshold

    def model_fingerprint(self) -> str:
        preset = get_preset(self.resolved_preset_id())
        return (
            f"{preset.id.value}|det={self.det_size}"
            f"|age={self.resolved_age_backend_id().value}"
        )


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILENAME


def load_settings() -> AppSettings:
    path = settings_path()
    if not path.is_file():
        return AppSettings(model_preset=default_preset_id().value)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppSettings(model_preset=default_preset_id().value)
        allowed = {field.name for field in fields(AppSettings)}
        filtered = {key: value for key, value in raw.items() if key in allowed}
        settings = AppSettings(**filtered)
        # Validate preset / age backend ids; fall back quietly.
        settings.resolved_preset_id()
        settings.age_backend = settings.resolved_age_backend_id().value
        return settings
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load settings from %s: %s", path, exc)
        return AppSettings(model_preset=default_preset_id().value)


def save_settings(settings: AppSettings) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Settings saved to %s", path)
    return path
