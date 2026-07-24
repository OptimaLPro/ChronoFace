"""MiVOLO v2 age estimator (Hugging Face transformers, optional GPU)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.utils.logging import get_logger
from src.utils.paths import project_root
from src.vision.interfaces import AgeEstimator

logger = get_logger("vision.mivolo_age")

MIVOLO_HF_ID = "iitolstykh/mivolo_v2"

_IMPORT_ERROR: str | None = None
try:
    import torch
except Exception as exc:  # noqa: BLE001
    torch = None  # type: ignore[assignment]
    _IMPORT_ERROR = f"torch not available: {exc}"


def _ensure_torch() -> bool:
    """Import torch, retrying after an in-app pip install."""
    global torch, _IMPORT_ERROR
    if torch is not None:
        return True
    try:
        import torch as _torch

        torch = _torch
        _IMPORT_ERROR = None
        return True
    except Exception as exc:  # noqa: BLE001
        _IMPORT_ERROR = f"torch not available: {exc}"
        return False


def mivolo_available() -> bool:
    if not _ensure_torch():
        return False
    try:
        import transformers  # noqa: F401
        import torchvision  # noqa: F401
        import mivolo  # noqa: F401
        import timm  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def mivolo_import_error() -> str | None:
    if not _ensure_torch():
        return (
            _IMPORT_ERROR
            or "The AI engine (PyTorch) is not installed yet."
        )
    try:
        import transformers  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return f"Supporting libraries missing: {exc}"
    try:
        import torchvision  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return f"Torchvision missing: {exc}"
    try:
        import mivolo  # noqa: F401
        import timm  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return f"Age model package (MiVOLO) missing: {exc}"
    return None


def mivolo_cache_dir() -> Path:
    path = project_root() / "models" / "mivolo_v2"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mivolo_installed() -> bool:
    """True when HF snapshot files are present under models/mivolo_v2."""
    cache = mivolo_cache_dir()
    # transformers stores snapshots under cache; also accept direct config.json
    if (cache / "config.json").is_file():
        return True
    snapshots = cache / "models--iitolstykh--mivolo_v2" / "snapshots"
    if snapshots.is_dir() and any(snapshots.iterdir()):
        return True
    return False


def resolve_mivolo_device() -> str:
    if torch is None:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def ensure_mivolo_model(*, download: bool = True) -> Path:
    """
    Ensure MiVOLO v2 weights are cached locally.

    Returns the local cache directory. Raises if dependencies are missing
    or download is disabled and files are absent.
    """
    if not mivolo_available():
        raise RuntimeError(
            "The better age model needs a few extra pieces "
            "(PyTorch and related tools).\n\n"
            "Open Settings → Models, choose MiVOLO v2, and save — "
            "ChronoFace can install them for you.\n\n"
            f"Details: {mivolo_import_error()}"
        )
    cache = mivolo_cache_dir()
    if mivolo_installed() and not download:
        return cache
    if not download and not mivolo_installed():
        raise FileNotFoundError(f"MiVOLO v2 not downloaded yet: {cache}")

    from transformers import AutoConfig, AutoImageProcessor, AutoModelForImageClassification

    logger.info("Loading / downloading MiVOLO v2 into %s", cache)
    AutoConfig.from_pretrained(
        MIVOLO_HF_ID,
        trust_remote_code=True,
        cache_dir=str(cache),
    )
    AutoImageProcessor.from_pretrained(
        MIVOLO_HF_ID,
        trust_remote_code=True,
        cache_dir=str(cache),
    )
    AutoModelForImageClassification.from_pretrained(
        MIVOLO_HF_ID,
        trust_remote_code=True,
        cache_dir=str(cache),
    )
    logger.info("MiVOLO v2 ready at %s", cache)
    return cache


class MiVOLOAgeEstimator(AgeEstimator):
    """
    Estimate age from an aligned BGR face crop using MiVOLO v2.

    Uses face-only mode (no body crop). Prefer CUDA when available.
    """

    ignores_detector_model_age = True
    """Pipeline must not prefer InsightFace model_age over this estimator."""

    def __init__(self, *, device: str | None = None) -> None:
        if not mivolo_available():
            raise RuntimeError(
                "MiVOLO v2 is not available.\n\n"
                f"{mivolo_import_error()}"
            )
        assert torch is not None

        from transformers import (
            AutoConfig,
            AutoImageProcessor,
            AutoModelForImageClassification,
        )

        self.device = device or resolve_mivolo_device()
        cache = str(mivolo_cache_dir())
        dtype = torch.float16 if self.device.startswith("cuda") else torch.float32

        self._config = AutoConfig.from_pretrained(
            MIVOLO_HF_ID,
            trust_remote_code=True,
            cache_dir=cache,
        )
        self._processor = AutoImageProcessor.from_pretrained(
            MIVOLO_HF_ID,
            trust_remote_code=True,
            cache_dir=cache,
        )
        load_kwargs: dict = {
            "trust_remote_code": True,
            "cache_dir": cache,
        }
        # transformers renamed torch_dtype → dtype; support both.
        try:
            self._model = AutoModelForImageClassification.from_pretrained(
                MIVOLO_HF_ID,
                dtype=dtype,
                **load_kwargs,
            )
        except TypeError:
            self._model = AutoModelForImageClassification.from_pretrained(
                MIVOLO_HF_ID,
                torch_dtype=dtype,
                **load_kwargs,
            )
        self._model.to(self.device)
        self._model.eval()
        logger.info("MiVOLO v2 age estimator ready on %s (%s)", self.device, dtype)

    def estimate_age(self, face_image: Any) -> tuple[float, float]:
        if face_image is None or getattr(face_image, "size", 0) == 0:
            raise ValueError("Face image is empty")
        assert torch is not None

        crop = np.asarray(face_image)
        if crop.ndim != 3 or crop.shape[2] != 3:
            raise ValueError("Face image must be HxWx3 BGR")

        # Ensure minimum size — very tiny crops confuse the processor.
        height, width = crop.shape[:2]
        if min(height, width) < 32:
            scale = 32.0 / float(min(height, width))
            crop = cv2.resize(
                crop,
                (max(32, int(width * scale)), max(32, int(height * scale))),
                interpolation=cv2.INTER_LINEAR,
            )

        # Face-only: body crop omitted (None). Processor accepts BGR ndarrays.
        faces_input = self._processor(images=[crop])["pixel_values"]
        faces_input = faces_input.to(dtype=self._model.dtype, device=self.device)

        with torch.inference_mode():
            try:
                output = self._model(faces_input=faces_input, body_input=None)
            except TypeError:
                # Some remote-code revisions require an explicit empty body batch.
                body_input = torch.zeros_like(faces_input)
                output = self._model(faces_input=faces_input, body_input=body_input)

        age = float(output.age_output[0].item())
        age = float(max(0.0, min(100.0, age)))

        # Gender softmax as a soft confidence proxy when available.
        confidence = 0.72
        gender_probs = getattr(output, "gender_probs", None)
        if gender_probs is not None:
            try:
                confidence = float(
                    max(0.45, min(0.90, 0.55 + 0.35 * float(gender_probs[0].item())))
                )
            except Exception:  # noqa: BLE001
                confidence = 0.72

        # Slightly down-weight tiny/blurry crops.
        size_score = min(1.0, min(height, width) / 112.0)
        confidence = float(max(0.40, min(0.90, confidence * (0.75 + 0.25 * size_score))))
        return round(age, 2), round(confidence, 3)
