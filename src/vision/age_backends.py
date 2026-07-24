"""Selectable age-estimation backends (independent of identity model pack)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgeBackendId(str, Enum):
    """How facial age is estimated after faces are detected."""

    BUILTIN = "builtin"
    """InsightFace genderage (when using InsightFace) or EfficientNet (OpenCV)."""

    MIVOLO_V2 = "mivolo_v2"
    """Hugging Face MiVOLO v2 — stronger age model; needs torch + transformers."""


@dataclass(frozen=True)
class AgeBackendInfo:
    id: AgeBackendId
    title: str
    short_label: str
    summary: str
    details: str
    download_size: str
    ram_hint: str
    license_note: str
    requires_gpu_friendly: bool = False
    recommended: bool = False


AGE_BACKENDS: dict[AgeBackendId, AgeBackendInfo] = {
    AgeBackendId.BUILTIN: AgeBackendInfo(
        id=AgeBackendId.BUILTIN,
        title="Built-in (InsightFace / EfficientNet)",
        short_label="Built-in",
        summary=(
            "Uses the age head that ships with your identity pack "
            "(InsightFace genderage, or EfficientNet for OpenCV Fast)."
        ),
        details=(
            "No extra download beyond the identity model pack.\n"
            "Good enough with DOB + EXIF, but often inaccurate on kids/teens."
        ),
        download_size="Included",
        ram_hint="Low",
        license_note="Same as the selected identity model pack.",
        recommended=False,
    ),
    AgeBackendId.MIVOLO_V2: AgeBackendInfo(
        id=AgeBackendId.MIVOLO_V2,
        title="MiVOLO v2 (recommended for age)",
        short_label="MiVOLO v2",
        summary=(
            "State-of-the-art open age/gender transformer from "
            "WildChlamydia/MiVOLO (Hugging Face iitolstykh/mivolo_v2). "
            "Much better on children and teens than InsightFace genderage."
        ),
        details=(
            "Uses your graphics card when available (a GTX 1660 Ti is fine).\n"
            "Needs a few extra pieces on this computer (PyTorch and related tools) — "
            "ChronoFace can install them when you save this setting.\n"
            "First use downloads about 100 MB of model files.\n"
            "Face identity matching still uses your selected InsightFace/OpenCV pack."
        ),
        download_size="~100 MB",
        ram_hint="Medium (~1–2 GB VRAM / RAM)",
        license_note=(
            "MiVOLO research code/weights — personal / research use. "
            "See https://github.com/WildChlamydia/MiVOLO"
        ),
        requires_gpu_friendly=True,
        recommended=True,
    ),
}


def list_age_backends() -> list[AgeBackendInfo]:
    return [
        AGE_BACKENDS[AgeBackendId.BUILTIN],
        AGE_BACKENDS[AgeBackendId.MIVOLO_V2],
    ]


def get_age_backend(backend_id: AgeBackendId | str) -> AgeBackendInfo:
    if isinstance(backend_id, str):
        backend_id = AgeBackendId(backend_id)
    return AGE_BACKENDS[backend_id]


def default_age_backend_id() -> AgeBackendId:
    return AgeBackendId.BUILTIN
