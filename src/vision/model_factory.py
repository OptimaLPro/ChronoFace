"""Build detector / recognizer / age estimator from app settings."""

from __future__ import annotations

from dataclasses import dataclass

from src.settings.app_settings import AppSettings, load_settings
from src.utils.logging import get_logger
from src.vision.age_backends import AgeBackendId
from src.vision.age_estimator import EfficientNetAgeEstimator
from src.vision.face_detector import YuNetFaceDetector
from src.vision.face_embedder import SFaceEmbedder
from src.vision.insightface_backend import (
    InsightFaceAgeEstimator,
    InsightFaceDetector,
    InsightFaceEmbedder,
    InsightFaceSession,
    insightface_available,
)
from src.vision.interfaces import AgeEstimator, FaceDetector, FaceRecognizer
from src.vision.model_catalog import BackendFamily, get_preset
from src.vision.model_manager import (
    ensure_age_model,
    ensure_face_models,
    ensure_insightface_pack,
    insightface_root,
)

logger = get_logger("vision.model_factory")


@dataclass
class VisionStack:
    """Concrete vision backends selected by the user."""

    detector: FaceDetector
    embedder: FaceRecognizer
    age_estimator: AgeEstimator
    preset_id: str
    age_backend_id: str
    fingerprint: str
    match_threshold: float
    low_confidence_threshold: float


def _build_age_estimator(
    settings: AppSettings,
    *,
    builtin: AgeEstimator,
) -> AgeEstimator:
    """Optionally replace the pack's age head with MiVOLO v2."""
    backend = settings.resolved_age_backend_id()
    if backend != AgeBackendId.MIVOLO_V2:
        return builtin

    from src.vision.mivolo_age import (
        MiVOLOAgeEstimator,
        ensure_mivolo_model,
        mivolo_available,
        mivolo_import_error,
    )

    if not mivolo_available():
        raise RuntimeError(
            "Age backend “MiVOLO v2” is selected but dependencies are missing.\n\n"
            "Install with (GPU / GTX 1660 Ti):\n"
            "  pip install torch torchvision --index-url "
            "https://download.pytorch.org/whl/cu124\n"
            "  pip install transformers accelerate\n\n"
            f"Details: {mivolo_import_error()}\n\n"
            "Or switch Settings → Models → Age model back to Built-in."
        )
    ensure_mivolo_model(download=True)
    estimator = MiVOLOAgeEstimator()
    logger.info("Age backend: MiVOLO v2 (overrides pack age head)")
    return estimator


def create_vision_stack(settings: AppSettings | None = None) -> VisionStack:
    """Instantiate models for the active settings preset."""
    settings = settings or load_settings()
    preset = get_preset(settings.resolved_preset_id())
    match_threshold = settings.effective_match_threshold()
    low_confidence = settings.effective_low_confidence_threshold()
    fingerprint = settings.model_fingerprint()
    age_backend_id = settings.resolved_age_backend_id().value

    if preset.backend == BackendFamily.OPENCV:
        ensure_face_models(download=True)
        ensure_age_model(download=True)
        detector: FaceDetector = YuNetFaceDetector()
        embedder: FaceRecognizer = SFaceEmbedder(detector=detector)
        builtin_age: AgeEstimator = EfficientNetAgeEstimator()
        logger.info("Vision stack: OpenCV Fast")
    else:
        if not insightface_available():
            raise RuntimeError(
                "Selected model pack requires the 'insightface' package.\n\n"
                "Install it with:\n"
                "  pip install insightface onnx\n\n"
                "Or switch Settings → Models back to “OpenCV Fast”."
            )
        assert preset.pack_name is not None
        ensure_insightface_pack(preset.pack_name, download=True)
        session = InsightFaceSession(
            preset.pack_name,
            root=insightface_root(),
            det_size=settings.det_size,
        )
        detector = InsightFaceDetector(session)
        embedder = InsightFaceEmbedder(session)
        builtin_age = InsightFaceAgeEstimator(session)
        logger.info("Vision stack: InsightFace %s", preset.pack_name)

    age_estimator = _build_age_estimator(settings, builtin=builtin_age)

    return VisionStack(
        detector=detector,
        embedder=embedder,
        age_estimator=age_estimator,
        preset_id=preset.id.value,
        age_backend_id=age_backend_id,
        fingerprint=fingerprint,
        match_threshold=match_threshold,
        low_confidence_threshold=low_confidence,
    )
