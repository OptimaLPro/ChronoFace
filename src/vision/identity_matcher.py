"""Target-person identity matching against reference embeddings."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.domain.models import LifeStage
from src.vision.interfaces import DetectedFace


# OpenCV SFace recommended cosine threshold for same identity.
DEFAULT_MATCH_THRESHOLD = 0.363
LOW_CONFIDENCE_THRESHOLD = 0.30


@dataclass
class ReferenceEmbedding:
    embedding: np.ndarray
    life_stage: LifeStage = LifeStage.UNKNOWN
    source_path: str | None = None


@dataclass
class IdentityMatchResult:
    best_face_index: int | None
    identity_score: float
    target_found: bool
    low_confidence: bool
    matched_life_stage: LifeStage | None = None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for L2-normalized or raw vectors."""
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def best_identity_score(
    face_embedding: list[float] | np.ndarray,
    reference_embeddings: list[list[float]] | list[np.ndarray],
) -> float:
    """Compare one face embedding against reference embeddings; return best score."""
    if not reference_embeddings:
        return 0.0
    face = np.asarray(face_embedding, dtype=np.float64)
    scores = [
        cosine_similarity(face, np.asarray(reference, dtype=np.float64))
        for reference in reference_embeddings
    ]
    return max(scores) if scores else 0.0


def match_faces_to_references(
    faces: list[DetectedFace],
    references: list[ReferenceEmbedding],
    *,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> IdentityMatchResult:
    """
    Select the face most likely to be the target person.

    Compares every detected face against every reference embedding and picks
    the globally best score. Does not prefer the largest face.
    """
    if not faces or not references:
        return IdentityMatchResult(
            best_face_index=None,
            identity_score=0.0,
            target_found=False,
            low_confidence=False,
        )

    best_score = -1.0
    best_index: int | None = None
    best_stage: LifeStage | None = None

    for face_index, face in enumerate(faces):
        if face.embedding is None:
            continue
        for reference in references:
            score = cosine_similarity(face.embedding, reference.embedding)
            if score > best_score:
                best_score = score
                best_index = face_index
                best_stage = reference.life_stage

    if best_index is None:
        return IdentityMatchResult(
            best_face_index=None,
            identity_score=0.0,
            target_found=False,
            low_confidence=False,
        )

    target_found = best_score >= match_threshold
    low_confidence = (
        not target_found and best_score >= low_confidence_threshold
    )
    return IdentityMatchResult(
        best_face_index=best_index,
        identity_score=float(best_score),
        target_found=target_found,
        low_confidence=low_confidence,
        matched_life_stage=best_stage,
    )
