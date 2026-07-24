"""YuNet face detection via OpenCV FaceDetectorYN."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.vision.interfaces import DetectedFace, FaceDetector
from src.vision.model_manager import ensure_face_models
from src.utils.logging import get_logger

logger = get_logger("vision.face_detector")


class YuNetFaceDetector(FaceDetector):
    """
    Detect faces with OpenCV Zoo YuNet.

    Does not assume the largest face is the target person — callers must
    match embeddings against references.
    """

    def __init__(
        self,
        model_path: Path | None = None,
        *,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        top_k: int = 50,
    ) -> None:
        if model_path is None:
            model_path = ensure_face_models().detector
        self.model_path = Path(model_path)
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k
        self._detector = cv2.FaceDetectorYN.create(
            str(self.model_path),
            "",
            (320, 320),
            float(score_threshold),
            float(nms_threshold),
            int(top_k),
        )
        logger.info("YuNet detector loaded from %s", self.model_path)

    def detect(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        if image_bgr is None or image_bgr.size == 0:
            return []

        height, width = image_bgr.shape[:2]
        self._detector.setInputSize((width, height))
        _retval, faces = self._detector.detect(image_bgr)
        if faces is None:
            return []

        results: list[DetectedFace] = []
        for row in faces:
            x, y, w, h = [float(v) for v in row[:4]]
            score = float(row[-1])
            landmarks = np.array(row[4:14], dtype=np.float32).reshape(5, 2)
            results.append(
                DetectedFace(
                    bbox_x=x,
                    bbox_y=y,
                    bbox_w=w,
                    bbox_h=h,
                    detection_score=score,
                    landmarks=landmarks,
                )
            )
        return results


# Backwards-compatible name used by earlier stubs.
class NullFaceDetector(FaceDetector):
    def detect(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        raise NotImplementedError("Use YuNetFaceDetector instead.")
