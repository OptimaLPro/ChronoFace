"""Phase 3–5 face detection, identity matching, age estimation, and ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional, Sequence

from src.database.face_repository import FaceRecord, FaceRepository
from src.database.photo_repository import PhotoRepository
from src.domain.models import (
    PhotoRecord,
    ReferencePhoto,
    ReviewStatus,
    ScanSummary,
)
from src.metadata.age_from_dob import clamp_age_to_dob
from src.sorting.ranking import rank_photo_records
from src.sorting.scoring import apply_sort_decision, decide_sort_for_record
from src.settings.app_settings import AppSettings, load_settings, save_settings
from src.utils.logging import get_logger
from src.utils.paths import project_cache_dir
from src.vision.face_quality import estimate_face_quality
from src.vision.identity_matcher import (
    ReferenceEmbedding,
    match_faces_to_references,
)
from src.vision.interfaces import AgeEstimator, FaceDetector, FaceRecognizer
from src.vision.model_factory import VisionStack, create_vision_stack

logger = get_logger("workers.face_pipeline")

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]

FINGERPRINT_FILENAME = "analysis_model_fingerprint.txt"


def project_model_fingerprint_path(project_id: str) -> Path:
    return project_cache_dir(project_id) / FINGERPRINT_FILENAME


def read_project_model_fingerprint(project_id: str) -> str:
    path = project_model_fingerprint_path(project_id)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_project_model_fingerprint(project_id: str, fingerprint: str) -> None:
    path = project_model_fingerprint_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fingerprint.strip() + "\n", encoding="utf-8")


def project_needs_face_reprocess(
    project_id: str,
    settings: AppSettings | None = None,
) -> tuple[bool, str, str]:
    """
    Return (needs_reprocess, previous_fingerprint, current_fingerprint).

    True when this project was analyzed with a different model (or never
    stamped) than the one currently selected in Settings.
    """
    settings = settings or load_settings()
    current = settings.model_fingerprint()
    previous = read_project_model_fingerprint(project_id)
    if not settings.force_reprocess_after_model_change:
        return False, previous, current
    return previous != current, previous, current


@dataclass
class FacePipelineConfig:
    project_id: str
    reference_photos: Sequence[ReferencePhoto]
    date_of_birth: Optional[date] = None
    force_reprocess: bool = False
    match_threshold: float | None = None
    low_confidence_threshold: float | None = None
    settings: AppSettings | None = None


class FaceAnalysisPipeline:
    """Detect faces, match the target person, estimate age, and rank locally."""

    def __init__(
        self,
        config: FacePipelineConfig,
        *,
        detector: FaceDetector | None = None,
        embedder: FaceRecognizer | None = None,
        age_estimator: AgeEstimator | None = None,
        vision_stack: VisionStack | None = None,
    ) -> None:
        self.config = config
        self.photo_repo = PhotoRepository(config.project_id)
        self.face_repo = FaceRepository(config.project_id)
        self.cache_dir = project_cache_dir(config.project_id)
        self.faces_dir = self.cache_dir / "faces"
        self.embeddings_dir = self.cache_dir / "embeddings"
        self.ref_embeddings_dir = self.cache_dir / "reference_embeddings"
        self.faces_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings_dir.mkdir(parents=True, exist_ok=True)
        self.ref_embeddings_dir.mkdir(parents=True, exist_ok=True)

        settings = config.settings or load_settings()
        if vision_stack is None and (
            detector is None or embedder is None or age_estimator is None
        ):
            vision_stack = create_vision_stack(settings)

        if vision_stack is not None:
            self.detector = detector or vision_stack.detector
            self.embedder = embedder or vision_stack.embedder
            self.age_estimator = age_estimator or vision_stack.age_estimator
            self.match_threshold = (
                config.match_threshold
                if config.match_threshold is not None
                else vision_stack.match_threshold
            )
            self.low_confidence_threshold = (
                config.low_confidence_threshold
                if config.low_confidence_threshold is not None
                else vision_stack.low_confidence_threshold
            )
            self._model_fingerprint = vision_stack.fingerprint
        else:
            assert detector is not None and embedder is not None and age_estimator is not None
            self.detector = detector
            self.embedder = embedder
            self.age_estimator = age_estimator
            self.match_threshold = (
                config.match_threshold
                if config.match_threshold is not None
                else settings.effective_match_threshold()
            )
            self.low_confidence_threshold = (
                config.low_confidence_threshold
                if config.low_confidence_threshold is not None
                else settings.effective_low_confidence_threshold()
            )
            self._model_fingerprint = settings.model_fingerprint()

        self._settings = settings
        self._persist_fingerprint = vision_stack is not None
        previous = read_project_model_fingerprint(config.project_id)
        if settings.force_reprocess_after_model_change and (
            previous != self._model_fingerprint
        ):
            # Empty previous also counts as a mismatch — older scans had no stamp.
            logger.info(
                "Model mismatch for project %s (%s → %s); forcing face reprocess",
                config.project_id,
                previous or "(none)",
                self._model_fingerprint,
            )
            self.config.force_reprocess = True
        elif self.config.force_reprocess:
            logger.info("Face reprocess forced by caller")

    def run(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        base_summary: ScanSummary | None = None,
    ) -> ScanSummary:
        if self.config.force_reprocess and on_progress:
            on_progress(
                0,
                1,
                "Re-analyzing faces with the current model (cache ignored)…",
            )
        references = self._build_reference_embeddings()
        if on_progress:
            on_progress(0, 1, f"Built {len(references)} reference embeddings")

        photos = self.photo_repo.list_photos()
        total = len(photos)
        faces_processed = 0
        target_found = 0
        target_not_found = 0
        no_face = 0
        low_confidence = 0
        errors = 0
        cancelled = False

        for index, photo in enumerate(photos, start=1):
            if should_cancel and should_cancel():
                cancelled = True
                break

            if on_progress:
                on_progress(
                    index,
                    total,
                    f"Detecting faces… {photo.original_path.name}",
                )

            try:
                # Soft-removed photos stay out of analysis and export.
                if photo.review_status == ReviewStatus.EXCLUDED:
                    continue

                skip_full = self._should_skip_full_analysis(photo)
                if skip_full:
                    if (
                        photo.target_found
                        and photo.estimated_age is None
                        and photo.id is not None
                    ):
                        if on_progress:
                            on_progress(
                                index,
                                total,
                                f"Estimating age… {photo.original_path.name}",
                            )
                        self._fill_age_from_existing(photo)
                        faces_processed += 1

                    status = photo.review_status
                    if status == ReviewStatus.NO_FACE:
                        no_face += 1
                    elif status == ReviewStatus.TARGET_NOT_FOUND:
                        target_not_found += 1
                    elif status == ReviewStatus.LOW_CONFIDENCE:
                        low_confidence += 1
                    elif photo.target_found:
                        target_found += 1
                    continue

                result_status = self._process_photo(photo, references)
                faces_processed += 1
                if result_status == ReviewStatus.NO_FACE:
                    no_face += 1
                elif result_status == ReviewStatus.TARGET_NOT_FOUND:
                    target_not_found += 1
                elif result_status == ReviewStatus.LOW_CONFIDENCE:
                    low_confidence += 1
                elif result_status in {
                    ReviewStatus.PENDING,
                    ReviewStatus.NEEDS_REVIEW,
                    ReviewStatus.APPROVED,
                }:
                    target_found += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.exception("Face analysis failed for %s", photo.original_path)
                photo.review_status = ReviewStatus.ERROR
                photo.error_message = f"Face analysis error: {exc}"
                self.photo_repo.upsert(photo)

        if not cancelled:
            if on_progress:
                on_progress(total, total, "Ranking photos by age…")
            self._recompute_ranking()

        summary = base_summary or ScanSummary(
            total_discovered=total,
            processed=0,
            skipped_unchanged=0,
            errors=0,
            with_reliable_date=0,
            with_weak_date=0,
            with_no_date=0,
        )
        summary.cancelled = cancelled or summary.cancelled
        summary.errors += errors
        summary.faces_processed = faces_processed
        summary.target_found = target_found
        summary.target_not_found = target_not_found
        summary.no_face = no_face
        summary.low_confidence = low_confidence
        summary.reference_embeddings = len(references)
        if not cancelled and self._persist_fingerprint:
            write_project_model_fingerprint(
                self.config.project_id, self._model_fingerprint
            )
            self._settings.last_model_fingerprint = self._model_fingerprint
            save_settings(self._settings)
        logger.info(
            "Face analysis complete: found=%s not_found=%s no_face=%s low=%s",
            target_found,
            target_not_found,
            no_face,
            low_confidence,
        )
        return summary

    def reanalyze_photos(
        self,
        photo_ids: Sequence[int],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> list[PhotoRecord]:
        """
        Force face detection / matching / age estimation for specific photos.

        Used from Review to re-run analysis on one (or a few) selected photos
        without rescanning the whole folder.
        """
        wanted = {int(photo_id) for photo_id in photo_ids}
        if not wanted:
            return []

        references = self._build_reference_embeddings()
        photos = [
            photo
            for photo in self.photo_repo.list_photos()
            if photo.id is not None and photo.id in wanted
        ]
        total = len(photos)
        updated: list[PhotoRecord] = []

        for index, photo in enumerate(photos, start=1):
            if on_progress:
                on_progress(
                    index,
                    total,
                    f"Re-analyzing… {photo.original_path.name}",
                )
            # Drop cached faces so matching runs fresh for this photo.
            if photo.id is not None:
                self.face_repo.replace_faces_for_photo(photo.id, [])
            self._process_photo(photo, references)
            updated.append(photo)

        if on_progress:
            on_progress(total, total, "Updating age ranking…")
        self._recompute_ranking()
        # Return latest rows after ranking rewrite.
        latest = {
            photo.id: photo
            for photo in self.photo_repo.list_photos()
            if photo.id is not None and photo.id in wanted
        }
        return [latest[pid] for pid in wanted if pid in latest]

    def _should_skip_full_analysis(self, photo: PhotoRecord) -> bool:
        if self.config.force_reprocess:
            return False
        if photo.id is None:
            return False
        if photo.review_status == ReviewStatus.ERROR and not photo.target_found:
            if photo.error_message and photo.error_message.startswith("Face analysis"):
                return False
        existing = self.face_repo.list_faces_for_photo(photo.id)
        if existing:
            return True
        if photo.review_status in {
            ReviewStatus.NO_FACE,
            ReviewStatus.TARGET_NOT_FOUND,
            ReviewStatus.LOW_CONFIDENCE,
        }:
            return True
        if photo.target_found and photo.identity_score is not None:
            return True
        return False

    def _recompute_ranking(self) -> None:
        photos = self.photo_repo.list_photos()
        ranked = rank_photo_records(
            photos,
            date_of_birth=self.config.date_of_birth,
        )
        for photo in ranked:
            self.photo_repo.upsert(photo)

    def _fill_age_from_existing(self, photo: PhotoRecord) -> None:
        """Estimate age for an already-matched photo using its saved face crop."""
        if photo.id is None or not photo.target_found:
            return
        faces = self.face_repo.list_faces_for_photo(photo.id)
        selected = next((face for face in faces if face.is_selected_target), None)
        if selected is None or not selected.face_crop_path:
            decision = decide_sort_for_record(
                photo, date_of_birth=self.config.date_of_birth
            )
            apply_sort_decision(
                photo, decision, date_of_birth=self.config.date_of_birth
            )
            self.photo_repo.upsert(photo)
            return

        from src.utils.image_utils import read_image_bgr

        # Fill missing per-face ages, then clamp only the selected face onto the photo.
        for face in faces:
            if face.estimated_age is not None or not face.face_crop_path:
                continue
            try:
                crop = read_image_bgr(face.face_crop_path)
                raw_age, _confidence = self.age_estimator.estimate_age(crop)
                face.estimated_age = float(max(0.0, min(100.0, float(raw_age))))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Age fill failed for face %s in %s: %s",
                    face.id,
                    photo.original_path.name,
                    exc,
                )

        if selected.estimated_age is not None:
            raw_age = float(selected.estimated_age)
            photo.estimated_age = raw_age
            _clamped, was_clamped = clamp_age_to_dob(
                raw_age,
                self.config.date_of_birth,
            )
            photo.age_confidence = 0.25 if was_clamped else 0.6
        self.face_repo.replace_faces_for_photo(photo.id, faces)
        decision = decide_sort_for_record(
            photo, date_of_birth=self.config.date_of_birth
        )
        apply_sort_decision(
            photo, decision, date_of_birth=self.config.date_of_birth
        )
        self.photo_repo.upsert(photo)

    def _build_reference_embeddings(self) -> list[ReferenceEmbedding]:
        from src.utils.image_utils import read_image_bgr

        self.face_repo.clear_reference_embeddings()
        references: list[ReferenceEmbedding] = []
        problems: list[str] = []

        for index, reference in enumerate(self.config.reference_photos):
            path = Path(reference.file_path)
            if not path.is_file():
                message = f"missing file: {path.name}"
                logger.warning("Reference photo missing: %s", path)
                problems.append(message)
                continue

            try:
                image = read_image_bgr(path)
            except ValueError as exc:
                message = f"unreadable: {path.name} ({exc})"
                logger.warning("Could not read reference photo: %s", path)
                problems.append(message)
                continue

            faces = self.detector.detect(image)
            if not faces:
                message = f"no face detected: {path.name}"
                logger.warning("No face in reference photo: %s", path)
                problems.append(message)
                continue

            best = max(faces, key=lambda face: face.detection_score)
            enriched = self.embedder.align_and_embed(image, best)
            if enriched.embedding is None:
                problems.append(f"embedding failed: {path.name}")
                continue

            emb_path = self.ref_embeddings_dir / f"ref_{index:03d}.npy"
            FaceRepository.save_embedding(emb_path, enriched.embedding)
            self.face_repo.add_reference_embedding(
                source_path=path,
                life_stage=reference.life_stage,
                embedding_path=emb_path,
                detection_score=enriched.detection_score,
                reference_photo_id=reference.id,
            )
            references.append(
                ReferenceEmbedding(
                    embedding=enriched.embedding,
                    life_stage=reference.life_stage,
                    source_path=str(path),
                )
            )

        if not references:
            detail = "; ".join(problems) if problems else "unknown reason"
            raise RuntimeError(
                "Could not build any reference embeddings. "
                "Check that reference photos are readable and contain a clear face.\n\n"
                f"Details: {detail}"
            )
        return references

    def _process_photo(
        self,
        photo: PhotoRecord,
        references: list[ReferenceEmbedding],
    ) -> ReviewStatus:
        from src.utils.image_utils import read_image_bgr, write_image_bgr

        if photo.id is None:
            raise ValueError("Photo must be saved before face analysis")

        image = read_image_bgr(photo.original_path)

        detected = self.detector.detect(image)
        if not detected:
            photo.target_found = False
            photo.identity_score = 0.0
            photo.face_quality = 0.0
            photo.overall_confidence = 0.0
            photo.selected_face_id = None
            photo.review_status = ReviewStatus.NO_FACE
            photo.error_message = None
            self.face_repo.replace_faces_for_photo(photo.id, [])
            self.photo_repo.upsert(photo)
            return ReviewStatus.NO_FACE

        enriched_faces = []
        for face in detected:
            quality = estimate_face_quality(face, image.shape)
            face.quality_score = quality
            enriched_faces.append(self.embedder.align_and_embed(image, face))

        match = match_faces_to_references(
            enriched_faces,
            references,
            match_threshold=self.match_threshold,
            low_confidence_threshold=self.low_confidence_threshold,
        )

        face_records: list[FaceRecord] = []
        selected_db_id: int | None = None
        selected_face = (
            enriched_faces[match.best_face_index]
            if match.best_face_index is not None
            else None
        )

        # Estimate a raw AI age for every face (not only the selected target).
        # MiVOLO (and similar) must override InsightFace's built-in model_age.
        prefer_estimator = bool(
            getattr(self.age_estimator, "ignores_detector_model_age", False)
        )
        per_face_ages: list[float | None] = []
        per_face_confidence: list[float | None] = []
        for face in enriched_faces:
            face_age: float | None = None
            face_conf: float | None = None
            try:
                if (
                    not prefer_estimator
                    and face.model_age is not None
                ):
                    face_age = float(face.model_age)
                    face_conf = 0.70
                elif face.aligned_bgr is not None:
                    face_age, face_conf = self.age_estimator.estimate_age(
                        face.aligned_bgr
                    )
                    face_age = float(face_age)
                    face_conf = float(face_conf)
                elif face.model_age is not None:
                    # Fallback when crop missing but detector age exists.
                    face_age = float(face.model_age)
                    face_conf = 0.70
                # Keep face ages unclamped so adults vs kids stay distinguishable.
                if face_age is not None:
                    face_age = float(max(0.0, min(100.0, face_age)))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Age estimation failed for a face in %s: %s",
                    photo.original_path.name,
                    exc,
                )
                face_age = None
                face_conf = None
            per_face_ages.append(face_age)
            per_face_confidence.append(face_conf)

        # Photo stores the selected face's raw AI age; DOB ceiling applies in scoring.
        estimated_age: float | None = None
        age_confidence: float | None = None
        if (
            match.best_face_index is not None
            and (match.target_found or match.low_confidence)
        ):
            raw_selected = per_face_ages[match.best_face_index]
            raw_conf = per_face_confidence[match.best_face_index]
            if raw_selected is not None:
                estimated_age = float(raw_selected)
                if raw_conf is not None:
                    _clamped, was_clamped = clamp_age_to_dob(
                        estimated_age,
                        self.config.date_of_birth,
                    )
                    age_confidence = (
                        min(float(raw_conf), 0.25) if was_clamped else float(raw_conf)
                    )
                else:
                    age_confidence = None

        for index, face in enumerate(enriched_faces):
            is_selected = match.best_face_index == index
            emb_path = None
            crop_path = None
            if face.embedding is not None:
                emb_path = str(
                    FaceRepository.save_embedding(
                        self.embeddings_dir / f"photo_{photo.id}_face_{index}.npy",
                        face.embedding,
                    )
                )
            if face.aligned_bgr is not None:
                crop_path = str(self.faces_dir / f"photo_{photo.id}_face_{index}.jpg")
                write_image_bgr(crop_path, face.aligned_bgr)

            identity_score = None
            if face.embedding is not None:
                from src.vision.identity_matcher import best_identity_score

                identity_score = best_identity_score(
                    face.embedding,
                    [ref.embedding for ref in references],
                )

            face_records.append(
                FaceRecord(
                    photo_id=photo.id,
                    bbox_x=face.bbox_x,
                    bbox_y=face.bbox_y,
                    bbox_w=face.bbox_w,
                    bbox_h=face.bbox_h,
                    embedding_path=emb_path,
                    face_crop_path=crop_path,
                    quality_score=face.quality_score,
                    identity_score=identity_score,
                    estimated_age=per_face_ages[index],
                    is_selected_target=is_selected,
                )
            )

        saved_faces = self.face_repo.replace_faces_for_photo(photo.id, face_records)
        for face_record in saved_faces:
            if face_record.is_selected_target:
                selected_db_id = face_record.id
                break

        photo.identity_score = match.identity_score
        photo.selected_face_id = selected_db_id
        photo.error_message = None
        photo.estimated_age = estimated_age
        if age_confidence is not None:
            photo.age_confidence = age_confidence
        photo.face_quality = (
            selected_face.quality_score if selected_face is not None else 0.0
        )

        if match.target_found:
            photo.target_found = True
            photo.review_status = ReviewStatus.NEEDS_REVIEW
            photo.overall_confidence = min(
                1.0,
                0.7 * match.identity_score
                + 0.3 * (photo.face_quality or 0.0),
            )
            status = ReviewStatus.NEEDS_REVIEW
        elif match.low_confidence:
            photo.target_found = False
            photo.review_status = ReviewStatus.LOW_CONFIDENCE
            photo.overall_confidence = match.identity_score
            status = ReviewStatus.LOW_CONFIDENCE
        else:
            photo.target_found = False
            photo.review_status = ReviewStatus.TARGET_NOT_FOUND
            photo.overall_confidence = match.identity_score
            status = ReviewStatus.TARGET_NOT_FOUND

        decision = decide_sort_for_record(
            photo, date_of_birth=self.config.date_of_birth
        )
        apply_sort_decision(
            photo, decision, date_of_birth=self.config.date_of_birth
        )
        self.photo_repo.upsert(photo)
        return status
