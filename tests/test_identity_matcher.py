"""Tests for identity matching helpers."""

from __future__ import annotations

import numpy as np

from src.domain.models import LifeStage
from src.vision.identity_matcher import (
    ReferenceEmbedding,
    best_identity_score,
    cosine_similarity,
    match_faces_to_references,
)
from src.vision.interfaces import DetectedFace


def test_cosine_similarity_identical() -> None:
    vector = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    assert cosine_similarity(vector, vector) > 0.999


def test_best_identity_score_picks_max() -> None:
    face = [1.0, 0.0, 0.0]
    refs = [[0.0, 1.0, 0.0], [0.9, 0.1, 0.0]]
    score = best_identity_score(face, refs)
    assert score > 0.8


def test_match_faces_does_not_prefer_largest_face() -> None:
    # Face 0 is large but dissimilar; face 1 is small but matches.
    faces = [
        DetectedFace(
            bbox_x=0,
            bbox_y=0,
            bbox_w=400,
            bbox_h=400,
            detection_score=0.99,
            embedding=np.array([0.0, 1.0, 0.0], dtype=np.float32),
        ),
        DetectedFace(
            bbox_x=10,
            bbox_y=10,
            bbox_w=40,
            bbox_h=40,
            detection_score=0.80,
            embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32),
        ),
    ]
    references = [
        ReferenceEmbedding(
            embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32),
            life_stage=LifeStage.CHILDHOOD,
        )
    ]
    result = match_faces_to_references(faces, references, match_threshold=0.5)
    assert result.target_found is True
    assert result.best_face_index == 1
    assert result.identity_score > 0.9
