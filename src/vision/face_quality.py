"""Face quality scoring helpers."""

from __future__ import annotations

import math

import numpy as np

from src.vision.interfaces import DetectedFace


def estimate_face_quality(
    face: DetectedFace,
    image_shape: tuple[int, ...],
) -> float:
    """
    Return an approximate 0–1 quality score.

    Combines detector confidence with relative face size. Small or low-score
    faces get lower quality.
    """
    height = float(image_shape[0]) if image_shape else 1.0
    width = float(image_shape[1]) if len(image_shape) > 1 else 1.0
    image_area = max(height * width, 1.0)
    face_area = max(face.bbox_w, 1.0) * max(face.bbox_h, 1.0)
    size_ratio = face_area / image_area

    # Size contribution saturates around ~5% of the frame.
    size_score = min(1.0, math.sqrt(size_ratio / 0.05))
    det_score = max(0.0, min(1.0, float(face.detection_score)))
    quality = 0.65 * det_score + 0.35 * size_score
    return round(float(quality), 4)


def estimate_face_quality_from_image(face_image: np.ndarray) -> float:
    """Legacy helper for aligned crops when bbox context is unavailable."""
    if face_image is None or face_image.size == 0:
        return 0.0
    # Sharpness proxy via Laplacian variance on grayscale.
    import cv2

    if face_image.ndim == 3:
        gray = cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = face_image
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Empirically map typical variances into 0–1.
    return round(max(0.0, min(1.0, variance / 500.0)), 4)
