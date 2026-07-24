"""Copy photos to numbered export filenames without modifying originals."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.domain.models import PhotoRecord, ReviewStatus
from src.metadata.age_from_dob import clamp_age_to_dob
from src.sorting.grouping import age_group_label
from src.utils.logging import get_logger

logger = get_logger("export.file_exporter")

ProgressCallback = Callable[[int, int, str], None]


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
        planned.append(("main", index, photo, output_dir / name))

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
