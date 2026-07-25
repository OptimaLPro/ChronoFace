"""Copy photos to numbered export filenames without modifying originals."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.domain.match_status import is_no_match_photo
from src.domain.models import PhotoRecord, ReviewStatus
from src.metadata.age_from_dob import clamp_age_to_dob
from src.sorting.grouping import age_group_label
from src.utils.logging import get_logger

logger = get_logger("export.file_exporter")

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class AgeRangeFolder:
    """Inclusive age band that becomes a subfolder under the export root."""

    min_age: int
    max_age: int

    def __post_init__(self) -> None:
        if self.min_age < 0 or self.max_age < 0:
            raise ValueError("Age range bounds must be non-negative")
        if self.min_age > self.max_age:
            raise ValueError(
                f"Invalid age range: min ({self.min_age}) > max ({self.max_age})"
            )

    @property
    def folder_name(self) -> str:
        return f"{self.min_age}-{self.max_age}"

    def contains(self, age: int) -> bool:
        return self.min_age <= age <= self.max_age


@dataclass
class ExportOptions:
    """User choices for a numbered age-ordered export."""

    output_dir: Path
    include_age_in_name: bool = True
    export_matched: bool = True
    export_all_in_main: bool = False
    export_unresolved_separate: bool = True
    export_excluded_separate: bool = True
    write_csv: bool = True
    only_target_found: bool = True
    # When non-empty, main photos go into age-band subfolders (e.g. 0-2/).
    age_range_folders: list[AgeRangeFolder] = field(default_factory=list)


@dataclass
class ExportItem:
    photo: PhotoRecord
    destination: Path
    bucket: str  # main | unresolved | excluded


@dataclass
class ExportResult:
    exported_main: int = 0
    exported_unresolved: int = 0
    exported_excluded: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    csv_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    items: list[ExportItem] = field(default_factory=list)


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Make a filename safe for Windows Explorer and other filesystem tools."""
    cleaned = _UNSAFE_CHARS.sub("_", name).strip(" .")
    if not cleaned:
        cleaned = "photo"
    if len(cleaned) > max_length:
        stem = Path(cleaned).stem[: max_length - 8]
        suffix = Path(cleaned).suffix
        cleaned = f"{stem}{suffix}"
    return cleaned


def effective_age_for_name(
    photo: PhotoRecord,
    date_of_birth: date | None = None,
) -> float | None:
    if photo.manual_age is not None:
        return float(photo.manual_age)
    # No-match: still show the selected face's AI age on the timeline, but do
    # not invent chronology from DOB/capture date (e.g. dog must not show 12.6y).
    if is_no_match_photo(photo):
        if photo.estimated_age is not None:
            return float(photo.estimated_age)
        return None
    if photo.age_from_dob is not None:
        return float(photo.age_from_dob)
    if photo.estimated_age is not None:
        age, _ = clamp_age_to_dob(float(photo.estimated_age), date_of_birth)
        return age
    if photo.sort_score is not None:
        age, _ = clamp_age_to_dob(float(photo.sort_score), date_of_birth)
        return age
    return None


def build_export_filename(
    order: int,
    photo: PhotoRecord,
    *,
    include_age_in_name: bool,
) -> str:
    original = sanitize_filename(photo.original_path.name)
    stem = Path(original).stem
    suffix = photo.original_path.suffix.lower() or ".jpg"
    if include_age_in_name:
        age = effective_age_for_name(photo)
        if age is not None and age != float("inf"):
            age_token = f"{int(round(age)):02d}"
            return f"{order:04d}_age_{age_token}_{stem}{suffix}"
    return f"{order:04d}_{stem}{suffix}"


def classify_photo(photo: PhotoRecord) -> str:
    """Return main / unresolved / excluded bucket."""
    if photo.review_status == ReviewStatus.EXCLUDED:
        return "excluded"
    if photo.review_status in {
        ReviewStatus.NO_FACE,
        ReviewStatus.TARGET_NOT_FOUND,
        ReviewStatus.ERROR,
    }:
        return "excluded"
    if photo.review_status == ReviewStatus.LOW_CONFIDENCE:
        return "unresolved"
    if photo.target_found:
        return "main"
    return "excluded"


def age_range_subfolder(
    photo: PhotoRecord,
    ranges: list[AgeRangeFolder],
) -> str | None:
    """
    Subfolder name for a main-bucket photo when age ranges are configured.

    Returns ``None`` when no ranges are set (flat export). Photos with no
    usable age go to ``_unknown``; ages outside every range go to ``_other``.
    """
    if not ranges:
        return None
    age = effective_age_for_name(photo)
    if age is None or age == float("inf"):
        return "_unknown"
    rounded = int(round(age))
    for band in ranges:
        if band.contains(rounded):
            return band.folder_name
    return "_other"


def select_photos_for_export(
    photos: Iterable[PhotoRecord],
    options: ExportOptions,
) -> tuple[list[PhotoRecord], list[PhotoRecord], list[PhotoRecord]]:
    """
    Split photos into main / unresolved / excluded lists.

    ``photos`` should already be in desired sort order.
    """
    main: list[PhotoRecord] = []
    unresolved: list[PhotoRecord] = []
    excluded: list[PhotoRecord] = []

    for photo in photos:
        # Soft-removed from the project: keep the file on disk, never export.
        if photo.review_status == ReviewStatus.EXCLUDED:
            continue

        if options.export_all_in_main:
            main.append(photo)
            continue

        bucket = classify_photo(photo)
        if bucket == "main":
            main.append(photo)
        elif bucket == "unresolved":
            unresolved.append(photo)
        else:
            excluded.append(photo)

    return main, unresolved, excluded


def export_numbered_copies(
    photos: list[PhotoRecord],
    options: ExportOptions,
    *,
    on_progress: ProgressCallback | None = None,
) -> ExportResult:
    """
    Copy photos into numbered filenames under the output folder.

    Never modifies originals. Uses ``shutil.copy2`` to preserve metadata
    when the OS/filesystem allows it.
    """
    output_dir = Path(options.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    unresolved_dir = output_dir / "_unresolved"
    excluded_dir = output_dir / "_excluded"

    main, unresolved, excluded = select_photos_for_export(photos, options)

    planned: list[tuple[str, int, PhotoRecord, Path]] = []
    for index, photo in enumerate(main, start=1):
        name = build_export_filename(
            index, photo, include_age_in_name=options.include_age_in_name
        )
        sub = age_range_subfolder(photo, options.age_range_folders)
        dest_dir = output_dir / sub if sub else output_dir
        planned.append(("main", index, photo, dest_dir / name))

    if options.export_unresolved_separate:
        for index, photo in enumerate(unresolved, start=1):
            name = build_export_filename(
                index, photo, include_age_in_name=options.include_age_in_name
            )
            planned.append(("unresolved", index, photo, unresolved_dir / name))

    if options.export_excluded_separate:
        for index, photo in enumerate(excluded, start=1):
            name = build_export_filename(
                index, photo, include_age_in_name=options.include_age_in_name
            )
            planned.append(("excluded", index, photo, excluded_dir / name))

    result = ExportResult(output_dir=output_dir)
    total = len(planned)
    used_names: set[str] = set()

    for current, (bucket, _order, photo, destination) in enumerate(planned, start=1):
        if on_progress:
            on_progress(current, total, f"Exporting {photo.original_path.name}")

        destination = _unique_destination(destination, used_names)
        destination.parent.mkdir(parents=True, exist_ok=True)

        source = Path(photo.original_path)
        if not source.is_file():
            message = f"Missing source file: {source}"
            logger.warning(message)
            result.errors.append(message)
            result.skipped += 1
            continue

        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            message = f"Failed to copy {source.name}: {exc}"
            logger.exception(message)
            result.errors.append(message)
            result.skipped += 1
            continue

        item = ExportItem(photo=photo, destination=destination, bucket=bucket)
        result.items.append(item)
        if bucket == "main":
            result.exported_main += 1
        elif bucket == "unresolved":
            result.exported_unresolved += 1
        else:
            result.exported_excluded += 1

    logger.info(
        "Export complete: main=%s unresolved=%s excluded=%s errors=%s",
        result.exported_main,
        result.exported_unresolved,
        result.exported_excluded,
        len(result.errors),
    )
    return result


def _unique_destination(path: Path, used: set[str]) -> Path:
    candidate = path
    counter = 2
    key = str(candidate.resolve()) if candidate.parent.exists() else str(candidate)
    # Also avoid collisions within this export batch.
    while key.lower() in used or candidate.exists():
        candidate = path.with_name(f"{path.stem}__{counter}{path.suffix}")
        key = str(candidate)
        counter += 1
    used.add(key.lower())
    return candidate


def age_label_for_photo(photo: PhotoRecord) -> str:
    return age_group_label(effective_age_for_name(photo))
