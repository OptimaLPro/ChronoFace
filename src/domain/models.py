"""Core domain dataclasses and enums used across the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import uuid4


class LifeStage(str, Enum):
    """Optional life-stage grouping for reference photos."""

    BABY = "baby"
    CHILDHOOD = "childhood"
    TEENAGE = "teenage"
    ADULTHOOD = "adulthood"
    UNKNOWN = "unknown"


class ReviewStatus(str, Enum):
    """Review state for an analyzed photo."""

    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    NO_FACE = "no_face"
    TARGET_NOT_FOUND = "target_not_found"
    LOW_CONFIDENCE = "low_confidence"
    MANUALLY_CORRECTED = "manually_corrected"
    ERROR = "error"
    EXCLUDED = "excluded"


class DateReliability(str, Enum):
    """How trustworthy a photo's capture date is."""

    RELIABLE_EXIF = "reliable_exif"
    WEAK_FILESYSTEM = "weak_filesystem"
    NONE = "none"


@dataclass
class ReferencePhoto:
    """A user-selected reference image of the target person."""

    file_path: Path
    life_stage: LifeStage = LifeStage.UNKNOWN
    sort_order: int = 0
    id: Optional[int] = None


@dataclass
class ProjectConfig:
    """User-facing project settings (Phase 1)."""

    name: str
    input_folder: Path
    output_folder: Path
    date_of_birth: Optional[date] = None
    reference_photos: list[ReferencePhoto] = field(default_factory=list)
    include_subfolders: bool = True
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class PhotoRecord:
    """Persisted photo row after discovery / metadata processing."""

    project_id: str
    original_path: Path
    file_hash: str | None = None
    file_size: int | None = None
    mtime_ns: int | None = None
    thumbnail_path: Path | None = None
    capture_date: datetime | None = None
    date_reliability: DateReliability = DateReliability.NONE
    metadata_source: str | None = None
    filename_year: int | None = None
    age_from_dob: float | None = None
    file_created_at: datetime | None = None
    file_modified_at: datetime | None = None
    target_found: bool = False
    identity_score: float | None = None
    estimated_age: float | None = None
    age_confidence: float | None = None
    face_quality: float | None = None
    overall_confidence: float | None = None
    manual_age: float | None = None
    manual_order: int | None = None
    sort_score: float | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    selected_face_id: int | None = None
    error_message: str | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class PhotoAnalysis:
    """Per-photo analysis result used by ranking (later phases)."""

    path: Path
    target_found: bool
    identity_score: float
    estimated_age: float | None
    capture_date: datetime | None
    face_quality: float
    age_confidence: float
    overall_confidence: float
    manual_age: float | None = None
    manual_order: int | None = None
    date_reliability: DateReliability = DateReliability.NONE
    review_status: ReviewStatus = ReviewStatus.PENDING
    sort_score: float | None = None
    age_from_dob: float | None = None
    filename_year: int | None = None


@dataclass
class ScanSummary:
    """Summary returned after a metadata (+ optional face) scan."""

    total_discovered: int
    processed: int
    skipped_unchanged: int
    errors: int
    with_reliable_date: int
    with_weak_date: int
    with_no_date: int
    cancelled: bool = False
    faces_processed: int = 0
    target_found: int = 0
    target_not_found: int = 0
    no_face: int = 0
    low_confidence: int = 0
    reference_embeddings: int = 0
