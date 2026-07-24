"""User-driven identity corrections: reassign target face, add reference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

from src.database.face_repository import FaceRecord, FaceRepository
from src.database.photo_repository import PhotoRepository
from src.domain.models import LifeStage, PhotoRecord, ReviewStatus
from src.metadata.age_from_dob import clamp_age_to_dob
from src.sorting.scoring import apply_sort_decision, decide_sort_for_record
from src.utils.image_utils import read_image_bgr
from src.utils.logging import get_logger
from src.utils.paths import project_cache_dir
from src.vision.interfaces import AgeEstimator
from src.vision.model_factory import create_vision_stack

logger = get_logger("services.identity_correction")


@dataclass
class ReassignResult:
    photo: PhotoRecord
    face: FaceRecord


class IdentityCorrectionService:
    """Reassign the selected face for a photo and (optionally) learn from it."""

    def __init__(
        self,
        project_id: str,
        *,
        date_of_birth: Optional[date] = None,
        age_estimator: AgeEstimator | None = None,
    ) -> None:
        self.project_id = project_id
        self.date_of_birth = date_of_birth
        self.photo_repo = PhotoRepository(project_id)
        self.face_repo = FaceRepository(project_id)
        self._age_estimator = age_estimator
        self._ref_dir = project_cache_dir(project_id) / "reference_embeddings"
        self._ref_dir.mkdir(parents=True, exist_ok=True)

    def _get_age_estimator(self) -> AgeEstimator:
        if self._age_estimator is None:
            stack = create_vision_stack()
            self._age_estimator = stack.age_estimator
        return self._age_estimator

    def ensure_face_age(
        self, face: FaceRecord
    ) -> tuple[FaceRecord, float | None]:
        """
        Ensure the face has a raw AI age.

        Returns (face, age_confidence). Confidence is set when a new estimate
        is computed; None when a previously stored age is reused.
        """
        if face.estimated_age is not None:
            return face, None
        if not face.face_crop_path or not Path(face.face_crop_path).is_file():
            return face, None
        try:
            crop = read_image_bgr(face.face_crop_path)
            raw_age, confidence = self._get_age_estimator().estimate_age(crop)
            face.estimated_age = float(max(0.0, min(100.0, float(raw_age))))
            return face, float(confidence)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Age estimation failed for face %s: %s", face.id, exc)
            return face, None

    def reassign_target_face(
        self,
        photo: PhotoRecord,
        new_face_id: int,
        *,
        also_add_as_reference: bool = False,
        reference_life_stage: LifeStage = LifeStage.UNKNOWN,
    ) -> ReassignResult:
        """
        Point the photo at a different detected face and refresh derived fields.

        Recomputes:
          - photo.selected_face_id, target_found, identity_score
          - photo.face_quality
          - photo.estimated_age / age_confidence (from the new face's age)
          - photo.review_status (moves to MANUALLY_CORRECTED)
          - sort score
        """
        if photo.id is None:
            raise ValueError("Photo must be saved before reassigning faces")

        new_face = self.face_repo.get_face(new_face_id)
        if new_face is None or new_face.photo_id != photo.id:
            raise ValueError("Selected face does not belong to this photo")

        # Prefer the face's own stored age; estimate once if older scans omitted it.
        new_face, estimated_confidence = self.ensure_face_age(new_face)
        raw_age = (
            float(new_face.estimated_age)
            if new_face.estimated_age is not None
            else None
        )
        age_confidence: float | None = None
        if raw_age is not None:
            _clamped, was_clamped = clamp_age_to_dob(raw_age, self.date_of_birth)
            if was_clamped:
                age_confidence = 0.25
            elif estimated_confidence is not None:
                age_confidence = estimated_confidence
            else:
                age_confidence = 0.70

        updated_face = self.face_repo.set_selected_face(
            photo.id,
            new_face_id,
            estimated_age=raw_age,
        )
        if updated_face is None:
            raise RuntimeError("Face reassignment could not be persisted")
        # Keep the raw per-face age on the returned record.
        if raw_age is not None:
            updated_face.estimated_age = raw_age

        photo.selected_face_id = updated_face.id
        photo.target_found = True
        photo.identity_score = updated_face.identity_score or photo.identity_score
        photo.face_quality = updated_face.quality_score or photo.face_quality
        # Photo AI age tracks the selected face's raw estimate (not DOB-clamped).
        if raw_age is not None:
            photo.estimated_age = raw_age
        if age_confidence is not None:
            photo.age_confidence = age_confidence
        photo.review_status = ReviewStatus.MANUALLY_CORRECTED
        photo.overall_confidence = max(
            photo.overall_confidence or 0.0,
            min(
                1.0,
                0.7 * (photo.identity_score or 0.0)
                + 0.3 * (photo.face_quality or 0.0),
            ),
        )
        photo.error_message = None

        decision = decide_sort_for_record(photo, date_of_birth=self.date_of_birth)
        apply_sort_decision(
            photo, decision, date_of_birth=self.date_of_birth
        )
        self.photo_repo.upsert(photo)

        if also_add_as_reference and updated_face.embedding_path:
            self._promote_to_reference(
                photo=photo,
                face=updated_face,
                life_stage=reference_life_stage,
            )

        return ReassignResult(photo=photo, face=updated_face)

    def add_face_as_reference(
        self,
        photo: PhotoRecord,
        face_id: int,
        *,
        life_stage: LifeStage = LifeStage.UNKNOWN,
    ) -> Path:
        face = self.face_repo.get_face(face_id)
        if face is None or face.embedding_path is None:
            raise ValueError("Selected face has no saved embedding to promote")
        return self._promote_to_reference(
            photo=photo,
            face=face,
            life_stage=life_stage,
        )

    def _promote_to_reference(
        self,
        *,
        photo: PhotoRecord,
        face: FaceRecord,
        life_stage: LifeStage,
    ) -> Path:
        assert face.embedding_path is not None
        embedding = np.load(face.embedding_path)
        dest = self._ref_dir / f"manual_photo_{photo.id}_face_{face.id}.npy"
        FaceRepository.save_embedding(dest, embedding)
        self.face_repo.add_reference_embedding(
            source_path=photo.original_path,
            life_stage=life_stage,
            embedding_path=dest,
            detection_score=face.identity_score,
        )
        logger.info(
            "Added face %s from photo %s as reference (stage=%s)",
            face.id,
            photo.id,
            life_stage.value,
        )
        return dest
