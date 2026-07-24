"""SFace embedding generation via OpenCV FaceRecognizerSF."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.vision.face_detector import YuNetFaceDetector
from src.vision.interfaces import DetectedFace, FaceDetector, FaceRecognizer
from src.vision.model_manager import ensure_face_models
from src.utils.logging import get_logger

logger = get_logger("vision.face_embedder")


class SFaceEmbedder(FaceRecognizer):
    """Align detected faces and produce SFace identity embeddings."""

    def __init__(
        self,
        model_path: Path | None = None,
        detector: FaceDetector | None = None,
    ) -> None:
        if model_path is None:
            model_path = ensure_face_models().recognizer
        self.model_path = Path(model_path)
        self._recognizer = cv2.FaceRecognizerSF.create(str(self.model_path), "")
        self._detector = detector or YuNetFaceDetector()
        logger.info("SFace recognizer loaded from %s", self.model_path)

    def align_and_embed(
        self,
        image_bgr: np.ndarray,
        face: DetectedFace,
    ) -> DetectedFace:
        face_row = self._face_to_opencv_row(face)
        aligned = self._recognizer.alignCrop(image_bgr, face_row)
        feature = self._recognizer.feature(aligned)
        embedding = np.asarray(feature, dtype=np.float32).reshape(-1)

        return DetectedFace(
            bbox_x=face.bbox_x,
            bbox_y=face.bbox_y,
            bbox_w=face.bbox_w,
            bbox_h=face.bbox_h,
            detection_score=face.detection_score,
            landmarks=face.landmarks,
            aligned_bgr=aligned,
            embedding=embedding,
            quality_score=face.quality_score,
        )

    def create_embedding(self, image_path: Path) -> list[float]:
        from src.utils.image_utils import read_image_bgr

        image = read_image_bgr(image_path)
        faces = self._detector.detect(image)
        if not faces:
            raise ValueError(f"No face detected in reference image: {image_path}")
        # For a dedicated reference photo, prefer the highest-confidence detection.
        best = max(faces, key=lambda f: f.detection_score)
        enriched = self.align_and_embed(image, best)
        assert enriched.embedding is not None
        return enriched.embedding.astype(float).tolist()

    def match_cosine(self, embedding_a: np.ndarray, embedding_b: np.ndarray) -> float:
        """Return cosine similarity (higher is more similar, max ~1.0)."""
        a = np.asarray(embedding_a, dtype=np.float32).reshape(1, -1)
        b = np.asarray(embedding_b, dtype=np.float32).reshape(1, -1)
        return float(
            self._recognizer.match(a, b, cv2.FaceRecognizerSF_FR_COSINE)
        )

    @staticmethod
    def _face_to_opencv_row(face: DetectedFace) -> np.ndarray:
        """
        Build the 15-float face row expected by FaceRecognizerSF.alignCrop.

        Layout: x, y, w, h, 5×(lx, ly), score
        """
        row = np.zeros((15,), dtype=np.float32)
        row[0:4] = [face.bbox_x, face.bbox_y, face.bbox_w, face.bbox_h]
        if face.landmarks is not None:
            row[4:14] = np.asarray(face.landmarks, dtype=np.float32).reshape(-1)
        row[14] = face.detection_score
        return row


class NullFaceEmbedder(FaceRecognizer):
    def align_and_embed(
        self,
        image_bgr: np.ndarray,
        face: DetectedFace,
    ) -> DetectedFace:
        raise NotImplementedError("Use SFaceEmbedder instead.")

    def create_embedding(self, image_path: Path) -> list[float]:
        raise NotImplementedError("Use SFaceEmbedder instead.")
