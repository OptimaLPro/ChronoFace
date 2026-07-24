"""Facial age estimation via ONNX EfficientNet (FaceONNX-compatible)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort

from src.utils.logging import get_logger
from src.vision.interfaces import AgeEstimator
from src.vision.model_manager import ensure_age_model

logger = get_logger("vision.age_estimator")


@dataclass(frozen=True)
class AgeEstimate:
    """Approximate age prediction — never treat as an exact fact."""

    age: float
    confidence: float
    age_low: float
    age_high: float


class EfficientNetAgeEstimator(AgeEstimator):
    """
    Estimate age from an aligned BGR face crop.

    Model input: 1x3x224x224 ImageNet-normalized RGB.
    Output: continuous age in years.
    """

    def __init__(self, model_path: Path | None = None) -> None:
        if model_path is None:
            model_path = ensure_age_model().estimator
        self.model_path = Path(model_path)
        self._session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        logger.info("Age estimator loaded from %s", self.model_path)

    def estimate_age(self, face_image: Any) -> tuple[float, float]:
        result = self.estimate(face_image)
        return result.age, result.confidence

    def estimate(self, face_image: np.ndarray) -> AgeEstimate:
        if face_image is None or getattr(face_image, "size", 0) == 0:
            raise ValueError("Face image is empty")

        tensor = self._preprocess(face_image)
        outputs = self._session.run(None, {self._input_name: tensor})
        age = float(np.asarray(outputs[-1]).reshape(-1)[0])
        age = float(max(0.0, min(100.0, age)))

        # Heuristic confidence: sharper / larger crops tend to be more reliable,
        # but facial age is always approximate.
        confidence = self._confidence_from_crop(face_image)
        spread = 2.0 + (1.0 - confidence) * 6.0
        return AgeEstimate(
            age=round(age, 2),
            confidence=round(confidence, 3),
            age_low=round(max(0.0, age - spread), 1),
            age_high=round(age + spread, 1),
        )

    @staticmethod
    def _preprocess(image_bgr: np.ndarray) -> np.ndarray:
        if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
            raise ValueError("Face image must be HxWx3 BGR")
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_LINEAR)
        img = resized.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img = (img - mean) / std
        img = np.transpose(img, (2, 0, 1))
        return np.expand_dims(img, axis=0)

    @staticmethod
    def _confidence_from_crop(face_image: np.ndarray) -> float:
        height, width = face_image.shape[:2]
        size_score = min(1.0, min(height, width) / 112.0)
        gray = cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        sharp_score = max(0.0, min(1.0, sharpness / 400.0))
        confidence = 0.45 + 0.30 * size_score + 0.25 * sharp_score
        return float(max(0.35, min(0.85, confidence)))


class NullAgeEstimator(AgeEstimator):
    """Placeholder kept for interface compatibility in tests."""

    def estimate_age(self, face_image: Any) -> tuple[float, float]:
        raise NotImplementedError("Use EfficientNetAgeEstimator instead.")
