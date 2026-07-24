"""Phase 2 metadata scan pipeline (discovery, hash, EXIF, thumbnails)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from src.database.photo_repository import PhotoRepository
from src.domain.models import (
    DateReliability,
    PhotoRecord,
    ReviewStatus,
    ScanSummary,
)
from src.metadata.age_from_dob import age_from_dob_and_capture
from src.metadata.exif_reader import read_photo_metadata
from src.metadata.filename_parser import guess_year_from_name
from src.metadata.image_discovery import discover_images
from src.utils.hashing import sha256_file
from src.utils.image_utils import create_thumbnail, thumbnail_filename_for
from src.utils.logging import get_logger
from src.utils.paths import project_cache_dir

logger = get_logger("workers.metadata_pipeline")

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


@dataclass
class MetadataPipelineConfig:
    project_id: str
    input_folder: Path
    date_of_birth: Optional[date] = None
    recursive: bool = True
    force_reprocess: bool = False


class MetadataPipeline:
    """Scan an input folder and persist metadata + thumbnails locally."""

    def __init__(self, config: MetadataPipelineConfig) -> None:
        self.config = config
        self.photo_repo = PhotoRepository(config.project_id)
        self.cache_dir = project_cache_dir(config.project_id)
        self.thumbs_dir = self.cache_dir / "thumbnails"
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> ScanSummary:
        images = discover_images(self.config.input_folder, recursive=self.config.recursive)
        total = len(images)
        processed = 0
        skipped = 0
        errors = 0
        reliable = 0
        weak = 0
        none = 0
        cancelled = False

        if on_progress:
            on_progress(0, total, f"Found {total} images…")

        keep_paths: set[str] = set()

        for index, path in enumerate(images, start=1):
            if should_cancel and should_cancel():
                cancelled = True
                logger.info("Metadata scan cancelled after %s files", index - 1)
                break

            keep_paths.add(str(path.resolve()))
            if on_progress:
                on_progress(index, total, f"Processing {path.name}")

            try:
                record, was_skipped = self._process_one(path)
                if was_skipped:
                    skipped += 1
                else:
                    processed += 1

                if record.date_reliability == DateReliability.RELIABLE_EXIF:
                    reliable += 1
                elif record.date_reliability == DateReliability.WEAK_FILESYSTEM:
                    weak += 1
                else:
                    none += 1

                if record.review_status == ReviewStatus.ERROR:
                    errors += 1
            except Exception as exc:  # noqa: BLE001 — continue after file errors
                errors += 1
                logger.exception("Failed processing %s", path)
                self._save_error_record(path, str(exc))
                none += 1

        if not cancelled:
            self.photo_repo.delete_missing_paths(keep_paths)

        summary = ScanSummary(
            total_discovered=total,
            processed=processed,
            skipped_unchanged=skipped,
            errors=errors,
            with_reliable_date=reliable,
            with_weak_date=weak,
            with_no_date=none,
            cancelled=cancelled,
        )
        logger.info("Metadata scan complete: %s", summary)
        return summary

    def _process_one(self, path: Path) -> tuple[PhotoRecord, bool]:
        stat = path.stat()
        existing = self.photo_repo.get_by_path(path)

        # Soft-removed from the project: leave the file on disk, skip re-import.
        if existing is not None and existing.review_status == ReviewStatus.EXCLUDED:
            return existing, True

        unchanged = (
            existing is not None
            and existing.file_size == stat.st_size
            and existing.mtime_ns == stat.st_mtime_ns
            and existing.file_hash
            and existing.thumbnail_path
            and Path(existing.thumbnail_path).is_file()
            and not self.config.force_reprocess
        )
        if unchanged and existing is not None:
            return existing, True

        file_hash = sha256_file(path)
        thumb_path = self.thumbs_dir / thumbnail_filename_for(file_hash)

        error_message: str | None = None
        review_status = ReviewStatus.PENDING
        try:
            if not thumb_path.is_file() or self.config.force_reprocess:
                create_thumbnail(path, thumb_path)
        except ValueError as exc:
            error_message = str(exc)
            review_status = ReviewStatus.ERROR
            thumb_path_value: Path | None = None
        else:
            thumb_path_value = thumb_path

        metadata = read_photo_metadata(path)
        filename_year = guess_year_from_name(path)
        age_from_dob = age_from_dob_and_capture(
            self.config.date_of_birth,
            metadata.capture_date
            if metadata.reliability == DateReliability.RELIABLE_EXIF
            else None,
        )

        # Provisional sort score from DOB age or capture date ordinal.
        sort_score: float | None = None
        if age_from_dob is not None:
            sort_score = age_from_dob
        elif (
            metadata.capture_date is not None
            and metadata.reliability == DateReliability.RELIABLE_EXIF
        ):
            sort_score = metadata.capture_date.timestamp() / (365.25 * 24 * 3600)

        record = PhotoRecord(
            project_id=self.config.project_id,
            original_path=path.resolve(),
            file_hash=file_hash,
            file_size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            thumbnail_path=thumb_path_value,
            capture_date=metadata.capture_date,
            date_reliability=metadata.reliability,
            metadata_source=metadata.source,
            filename_year=filename_year,
            age_from_dob=age_from_dob,
            file_created_at=metadata.file_created_at,
            file_modified_at=metadata.file_modified_at,
            sort_score=sort_score,
            review_status=review_status,
            error_message=error_message,
        )
        saved = self.photo_repo.upsert(record)
        return saved, False

    def _save_error_record(self, path: Path, message: str) -> None:
        try:
            stat = path.stat()
            file_size = stat.st_size
            mtime_ns = stat.st_mtime_ns
        except OSError:
            file_size = None
            mtime_ns = None

        record = PhotoRecord(
            project_id=self.config.project_id,
            original_path=path.resolve(),
            file_size=file_size,
            mtime_ns=mtime_ns,
            review_status=ReviewStatus.ERROR,
            error_message=message,
            date_reliability=DateReliability.NONE,
            metadata_source="error",
        )
        self.photo_repo.upsert(record)
