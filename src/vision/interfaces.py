"""Replaceable vision model interfaces (licensing-safe abstraction)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class DetectedFace:
    """One detected face with geometry and optional embedding."""

    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float
    detection_score: float
    landmarks: np.ndarray | None = None
    aligned_bgr: np.ndarray | None = None
    embedding: np.ndarray | None = None
    quality_score: float = 0.0
    model_age: float | None = None
    """Age predicted by a multi-task model (e.g. InsightFace), if available."""


class FaceDetector(ABC):
    """Detect faces in an image."""

    @abstractmethod
    def detect(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        raise NotImplementedError

    def detect_path(self, image_path: Path) -> list[DetectedFace]:
        from src.utils.image_utils import read_image_bgr

        image = read_image_bgr(image_path)
        return self.detect(image)


class FaceRecognizer(ABC):
    """Align faces and create identity embeddings."""

    @abstractmethod
    def align_and_embed(
        self,
        image_bgr: np.ndarray,
        face: DetectedFace,
    ) -> DetectedFace:
        """Return a copy of ``face`` with aligned crop and embedding filled in."""
        raise NotImplementedError

    @abstractmethod
    def create_embedding(self, image_path: Path) -> list[float]:
        """Embed the best/largest face in an image (convenience API)."""
        raise NotImplementedError


class AgeEstimator(ABC):
    """Estimate age from an aligned face crop."""

    @abstractmethod
    def estimate_age(self, face_image: Any) -> tuple[float, float]:
        """
        Return (estimated_age, confidence).

        Confidence is a 0–1 value; treat age as approximate, never exact.
        """
        raise NotImplementedError
