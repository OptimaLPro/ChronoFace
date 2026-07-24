"""InsightFace-backed detector / recognizer / age estimator for personal use."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.utils.image_utils import read_image_bgr
from src.utils.logging import get_logger
from src.vision.interfaces import AgeEstimator, DetectedFace, FaceDetector, FaceRecognizer

logger = get_logger("vision.insightface_backend")


def insightface_available() -> bool:
    try:
        import insightface  # noqa: F401
        from insightface.app import FaceAnalysis  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def insightface_import_error() -> str | None:
    try:
        import insightface  # noqa: F401
        from insightface.app import FaceAnalysis  # noqa: F401

        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


class InsightFaceSession:
    """Shared FaceAnalysis instance for one model pack."""

    def __init__(
        self,
        pack_name: str,
        *,
        root: Path,
        det_size: int = 640,
    ) -> None:
        if not insightface_available():
            detail = insightface_import_error() or "unknown import error"
            raise RuntimeError(
                "InsightFace is not installed. Install with:\n"
                "  pip install insightface onnx\n\n"
                f"Details: {detail}"
            )

        from insightface.app import FaceAnalysis

        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.pack_name = pack_name
        self.root = root
        self.det_size = int(det_size)
        # Prefer CPU; CUDA is used automatically when available in the runtime.
        providers = ["CPUExecutionProvider"]
        try:
            import onnxruntime as ort

            available = ort.get_available_providers()
            if "CUDAExecutionProvider" in available:
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        except Exception:  # noqa: BLE001
            pass

        self.app = FaceAnalysis(
            name=pack_name,
            root=str(root),
            providers=providers,
        )
        # ctx_id=-1 forces CPU in older insightface builds; 0 is fine with providers.
        self.app.prepare(ctx_id=0, det_size=(self.det_size, self.det_size))
        logger.info(
            "InsightFace pack '%s' ready (det_size=%s, root=%s)",
            pack_name,
            self.det_size,
            root,
        )

    def analyze(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            return []
        faces = self.app.get(image_bgr)
        results: list[DetectedFace] = []
        height, width = image_bgr.shape[:2]
        for face in faces:
            bbox = np.asarray(face.bbox, dtype=np.float32).reshape(-1)
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
            x = max(0.0, x1)
            y = max(0.0, y1)
            w = max(1.0, min(float(width) - x, x2 - x1))
            h = max(1.0, min(float(height) - y, y2 - y1))
            landmarks = None
            if getattr(face, "kps", None) is not None:
                landmarks = np.asarray(face.kps, dtype=np.float32).reshape(-1, 2)
            embedding = None
            if getattr(face, "embedding", None) is not None:
                embedding = np.asarray(face.embedding, dtype=np.float32).reshape(-1)
            aligned = _safe_crop(image_bgr, int(x), int(y), int(w), int(h))
            model_age = None
            if getattr(face, "age", None) is not None:
                try:
                    model_age = float(face.age)
                except (TypeError, ValueError):
                    model_age = None
            results.append(
                DetectedFace(
                    bbox_x=x,
                    bbox_y=y,
                    bbox_w=w,
                    bbox_h=h,
                    detection_score=float(getattr(face, "det_score", 0.0) or 0.0),
                    landmarks=landmarks,
                    aligned_bgr=aligned,
                    embedding=embedding,
                    quality_score=0.0,
                    model_age=model_age,
                )
            )
        return results


def _safe_crop(
    image_bgr: np.ndarray, x: int, y: int, w: int, h: int
) -> np.ndarray | None:
    height, width = image_bgr.shape[:2]
    x1 = max(0, min(width - 1, x))
    y1 = max(0, min(height - 1, y))
    x2 = max(x1 + 1, min(width, x + w))
    y2 = max(y1 + 1, min(height, y + h))
    crop = image_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return crop.copy()


class InsightFaceDetector(FaceDetector):
    """Detection that also fills embeddings / ages in one InsightFace pass."""

    def __init__(self, session: InsightFaceSession) -> None:
        self.session = session

    def detect(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        return self.session.analyze(image_bgr)


class InsightFaceEmbedder(FaceRecognizer):
    """
    Pass-through embedder for faces already enriched by InsightFaceDetector.

    If a face has no embedding (edge case), re-runs analysis and matches by bbox.
    """

    def __init__(self, session: InsightFaceSession) -> None:
        self.session = session

    def align_and_embed(
        self,
        image_bgr: np.ndarray,
        face: DetectedFace,
    ) -> DetectedFace:
        if face.embedding is not None:
            if face.aligned_bgr is None:
                face.aligned_bgr = _safe_crop(
                    image_bgr,
                    int(face.bbox_x),
                    int(face.bbox_y),
                    int(face.bbox_w),
                    int(face.bbox_h),
                )
            return face

        analyzed = self.session.analyze(image_bgr)
        if not analyzed:
            return face
        best = min(
            analyzed,
            key=lambda other: abs(other.bbox_x - face.bbox_x)
            + abs(other.bbox_y - face.bbox_y),
        )
        face.embedding = best.embedding
        face.aligned_bgr = best.aligned_bgr or face.aligned_bgr
        face.landmarks = best.landmarks if best.landmarks is not None else face.landmarks
        face.model_age = best.model_age if best.model_age is not None else face.model_age
        return face

    def create_embedding(self, image_path: Path) -> list[float]:
        image = read_image_bgr(image_path)
        faces = self.session.analyze(image)
        if not faces:
            raise ValueError(f"No face detected in reference image: {image_path}")
        best = max(faces, key=lambda face: face.detection_score)
        if best.embedding is None:
            raise ValueError(f"Embedding failed for reference image: {image_path}")
        return best.embedding.astype(float).tolist()


class InsightFaceAgeEstimator(AgeEstimator):
    """
    Prefer age already predicted by InsightFace; fall back to crop heuristics.

    ``estimate_age`` on a crop alone cannot recover the attribute head, so we
    use a lightweight sharpness/size confidence with a mid confidence prior when
    only a crop is available (e.g. after manual face reassignment).
    """

    def __init__(self, session: InsightFaceSession | None = None) -> None:
        self.session = session

    def estimate_age(self, face_image: Any) -> tuple[float, float]:
        if face_image is None or getattr(face_image, "size", 0) == 0:
            raise ValueError("Face image is empty")

        # If caller somehow passed a DetectedFace, use model_age.
        if isinstance(face_image, DetectedFace) and face_image.model_age is not None:
            return float(face_image.model_age), 0.70

        # Crop-only path: no attribute head available — return conservative estimate
        # based on nothing better than "unknown adult-ish" would be wrong.
        # Prefer calling with model_age from DetectedFace in the pipeline.
        # Here we use a tiny heuristic placeholder age from face aspect only if
        # EfficientNet isn't available — raise so pipeline can skip?
        # Better: try to run genderage if present on session.
        age = self._estimate_from_session_crop(face_image)
        confidence = _crop_confidence(face_image)
        return age, confidence

    def _estimate_from_session_crop(self, face_image: np.ndarray) -> float:
        if self.session is None:
            raise ValueError(
                "Age re-estimation needs a face with model_age or an age ONNX model."
            )
        # Re-run detector on the crop padded — InsightFace expects full scene ideally.
        # Pad the crop so detectors still fire.
        padded = cv2.copyMakeBorder(
            face_image, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=(0, 0, 0)
        )
        faces = self.session.analyze(padded)
        if faces and faces[0].model_age is not None:
            return float(faces[0].model_age)
        raise ValueError("InsightFace could not estimate age for this crop")


def _crop_confidence(face_image: np.ndarray) -> float:
    height, width = face_image.shape[:2]
    size_score = min(1.0, min(height, width) / 112.0)
    gray = cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharp_score = max(0.0, min(1.0, sharpness / 400.0))
    return float(max(0.35, min(0.80, 0.45 + 0.30 * size_score + 0.25 * sharp_score)))
