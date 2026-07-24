"""Catalog of supported local vision model presets for personal use."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModelPresetId(str, Enum):
    """High-level model packs the user can pick in Settings."""

    OPENCV_FAST = "opencv_fast"
    INSIGHTFACE_BUFFALO_S = "insightface_buffalo_s"
    INSIGHTFACE_BUFFALO_L = "insightface_buffalo_l"
    INSIGHTFACE_ANTELOPE_V2 = "insightface_antelopev2"


class BackendFamily(str, Enum):
    OPENCV = "opencv"
    INSIGHTFACE = "insightface"


@dataclass(frozen=True)
class ModelPreset:
    """User-facing description of a model pack."""

    id: ModelPresetId
    title: str
    short_label: str
    backend: BackendFamily
    pack_name: str | None
    """InsightFace pack name, or None for OpenCV."""

    speed: str
    """One of: Fastest / Fast / Medium / Slow."""

    quality: str
    """One of: Good / Better / Best / Maximum."""

    effort: str
    """Setup difficulty for the user."""

    download_size: str
    ram_hint: str
    license_note: str
    default_match_threshold: float
    default_low_confidence_threshold: float
    summary: str
    details: str
    recommended: bool = False


MODEL_PRESETS: dict[ModelPresetId, ModelPreset] = {
    ModelPresetId.OPENCV_FAST: ModelPreset(
        id=ModelPresetId.OPENCV_FAST,
        title="OpenCV Fast (YuNet + SFace + EfficientNet)",
        short_label="Fast / Easy",
        backend=BackendFamily.OPENCV,
        pack_name=None,
        speed="Fastest",
        quality="Good",
        effort="Easiest — works out of the box, tiny downloads",
        download_size="~40 MB",
        ram_hint="Low (~0.5 GB)",
        license_note=(
            "OpenCV Zoo models (Apache 2.0 ecosystem) + FaceONNX-style age model. "
            "Fine for personal use; safest choice if you later redistribute the app."
        ),
        default_match_threshold=0.363,
        default_low_confidence_threshold=0.30,
        summary=(
            "Lightest option. Great for quick scans and weaker PCs. "
            "Identity matching is solid but not state-of-the-art on hard group photos."
        ),
        details=(
            "Detection: YuNet (OpenCV FaceDetectorYN)\n"
            "Recognition: SFace (OpenCV FaceRecognizerSF)\n"
            "Age: EfficientNet-B2 (ONNX)\n\n"
            "Choose this when you want speed and simplicity. "
            "Re-analyze is fast. Accuracy drops on tiny/blurry faces or crowded scenes."
        ),
        recommended=False,
    ),
    ModelPresetId.INSIGHTFACE_BUFFALO_S: ModelPreset(
        id=ModelPresetId.INSIGHTFACE_BUFFALO_S,
        title="InsightFace buffalo_s (balanced)",
        short_label="Balanced",
        backend=BackendFamily.INSIGHTFACE,
        pack_name="buffalo_s",
        speed="Fast",
        quality="Better",
        effort="Easy — one-time ~160 MB download, needs insightface package",
        download_size="~159 MB",
        ram_hint="Medium (~1 GB)",
        license_note=(
            "InsightFace pretrained models: non-commercial / personal research use only. "
            "Perfect for your personal photo sorting; do not use commercially without a license."
        ),
        default_match_threshold=0.40,
        default_low_confidence_threshold=0.32,
        summary=(
            "Good balance of speed and accuracy. Smaller SCRFD detector + MobileFaceNet "
            "recognition. Strong upgrade over OpenCV for most family albums."
        ),
        details=(
            "Detection: SCRFD-500MF\n"
            "Recognition: MobileFaceNet @ WebFace600K\n"
            "Age/Gender: InsightFace attribute model\n\n"
            "Pick this if OpenCV misses people too often but you still want snappy scans."
        ),
    ),
    ModelPresetId.INSIGHTFACE_BUFFALO_L: ModelPreset(
        id=ModelPresetId.INSIGHTFACE_BUFFALO_L,
        title="InsightFace buffalo_l (recommended)",
        short_label="Best (recommended)",
        backend=BackendFamily.INSIGHTFACE,
        pack_name="buffalo_l",
        speed="Medium",
        quality="Best",
        effort="Moderate — ~326 MB download; best default for personal use",
        download_size="~326 MB",
        ram_hint="Medium–High (~1.5 GB)",
        license_note=(
            "InsightFace pretrained models: non-commercial / personal research use only. "
            "Ideal for personal, non-commercial projects like this app."
        ),
        default_match_threshold=0.42,
        default_low_confidence_threshold=0.34,
        summary=(
            "The best open-source pack for most people. ResNet50 ArcFace recognition "
            "plus a strong SCRFD detector. Handles group shots, different ages, and "
            "lighting much better than the Fast preset."
        ),
        details=(
            "Detection: SCRFD-10GF\n"
            "Recognition: ResNet50 @ WebFace600K (ArcFace)\n"
            "Age/Gender: InsightFace attribute model\n\n"
            "Recommended for personal use when you care about correct identity matching. "
            "Slower than OpenCV Fast, but usually worth it for accurate age-ordered sorting."
        ),
        recommended=True,
    ),
    ModelPresetId.INSIGHTFACE_ANTELOPE_V2: ModelPreset(
        id=ModelPresetId.INSIGHTFACE_ANTELOPE_V2,
        title="InsightFace antelopev2 (maximum)",
        short_label="Maximum quality",
        backend=BackendFamily.INSIGHTFACE,
        pack_name="antelopev2",
        speed="Slow",
        quality="Maximum",
        effort="Heavier — largest download; zip may nest folders (app auto-fixes)",
        download_size="~407 MB",
        ram_hint="High (~2 GB)",
        license_note=(
            "InsightFace pretrained models: non-commercial / personal research use only. "
            "Manual download may be required for some InsightFace versions."
        ),
        default_match_threshold=0.40,
        default_low_confidence_threshold=0.32,
        summary=(
            "Highest-quality open InsightFace pack (ResNet100). Use when buffalo_l still "
            "confuses lookalikes or hard angles. Slowest CPU option."
        ),
        details=(
            "Detection: RetinaFace / SCRFD-class high-capacity detector\n"
            "Recognition: ResNet100 @ Glint360K\n"
            "Age/Gender: InsightFace attribute model\n\n"
            "Only pick this if you have time for longer scans and want the strongest "
            "open-source identity model available in this app."
        ),
    ),
}


def list_presets() -> list[ModelPreset]:
    """Return presets in UI display order."""
    order = [
        ModelPresetId.OPENCV_FAST,
        ModelPresetId.INSIGHTFACE_BUFFALO_S,
        ModelPresetId.INSIGHTFACE_BUFFALO_L,
        ModelPresetId.INSIGHTFACE_ANTELOPE_V2,
    ]
    return [MODEL_PRESETS[preset_id] for preset_id in order]


def get_preset(preset_id: ModelPresetId | str) -> ModelPreset:
    if isinstance(preset_id, str):
        preset_id = ModelPresetId(preset_id)
    return MODEL_PRESETS[preset_id]


def default_preset_id() -> ModelPresetId:
    """Prefer buffalo_l when InsightFace is installed; otherwise OpenCV Fast."""
    try:
        from src.vision.insightface_backend import insightface_available

        if insightface_available():
            return ModelPresetId.INSIGHTFACE_BUFFALO_L
    except Exception:  # noqa: BLE001
        pass
    return ModelPresetId.OPENCV_FAST
