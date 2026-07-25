"""Exact duplicate detection via content hash (SHA-256)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from src.domain.models import DateReliability, PhotoRecord, ReviewStatus

# Filenames that look like OS / Explorer "copy" siblings of a primary file.
# Avoid bare _\d+ suffixes (camera names like IMG_2048).
_COPY_NAME_RE = re.compile(
    r"(?i)"
    r"(?:^copy\s+of\s+)"
    r"|(?:\scopy(?:\s*\(\d+\))?$)"
    r"|(?:\s-\s*copy(?:\s*\(\d+\))?$)"
    r"|(?:_copy(?:_\d+)?$)"
    r"|(?:\s\(\d+\)$)"
)

_STATUS_RANK = {
    ReviewStatus.APPROVED: 6,
    ReviewStatus.MANUALLY_CORRECTED: 5,
    ReviewStatus.NEEDS_REVIEW: 4,
    ReviewStatus.LOW_CONFIDENCE: 3,
    ReviewStatus.PENDING: 2,
    ReviewStatus.TARGET_NOT_FOUND: 1,
    ReviewStatus.NO_FACE: 1,
    ReviewStatus.ERROR: 0,
    ReviewStatus.EXCLUDED: -1,
}


@dataclass(frozen=True)
class DuplicateGroup:
    """One content-identical set: keep one, soft-remove the rest."""

    file_hash: str
    keeper: PhotoRecord
    duplicates: tuple[PhotoRecord, ...]

    @property
    def size(self) -> int:
        return 1 + len(self.duplicates)


@dataclass(frozen=True)
class DuplicateScanResult:
    """Outcome of scanning project photos for exact duplicates."""

    groups: tuple[DuplicateGroup, ...]
    skipped_no_hash: int = 0

    @property
    def group_count(self) -> int:
        return len(self.groups)

    @property
    def removable_count(self) -> int:
        return sum(len(group.duplicates) for group in self.groups)

    @property
    def has_duplicates(self) -> bool:
        return self.removable_count > 0


def looks_like_copy_filename(path: Path | str) -> bool:
    """True when the stem looks like a duplicate export / OS copy name."""
    stem = Path(path).stem.strip()
    return bool(_COPY_NAME_RE.search(stem))


def _keeper_sort_key(photo: PhotoRecord) -> tuple:
    """Higher tuple wins. Prefer curated, matched, primary-looking files."""
    status = _STATUS_RANK.get(photo.review_status, 0)
    identity = photo.identity_score if photo.identity_score is not None else -1.0
    quality = photo.face_quality if photo.face_quality is not None else -1.0
    overall = (
        photo.overall_confidence if photo.overall_confidence is not None else -1.0
    )
    has_manual = 1 if (
        photo.manual_order is not None or photo.manual_age is not None
    ) else 0
    reliable_date = 1 if photo.date_reliability is DateReliability.RELIABLE_EXIF else 0
    not_copy_name = 0 if looks_like_copy_filename(photo.original_path) else 1
    # Prefer earlier timeline placement when scores tie.
    sort_score = (
        -(photo.sort_score)
        if photo.sort_score is not None
        else float("-inf")
    )
    path_key = str(photo.original_path).lower()
    return (
        1 if photo.target_found else 0,
        status,
        has_manual,
        not_copy_name,
        reliable_date,
        identity,
        quality,
        overall,
        sort_score,
        # Prefer shorter path (often the "original" location).
        -len(path_key),
        path_key,
    )


def choose_keeper(photos: list[PhotoRecord]) -> PhotoRecord:
    """Pick the best photo to keep from an exact-duplicate set."""
    if not photos:
        raise ValueError("Cannot choose keeper from empty group")
    return max(photos, key=_keeper_sort_key)


def find_exact_duplicates(photos: list[PhotoRecord]) -> DuplicateScanResult:
    """
    Group active photos by SHA-256 ``file_hash``.

    Already-excluded photos are ignored. Photos without a hash are skipped
    (they cannot be proven identical without re-hashing).
    """
    by_hash: dict[str, list[PhotoRecord]] = defaultdict(list)
    skipped_no_hash = 0

    for photo in photos:
        if photo.review_status == ReviewStatus.EXCLUDED:
            continue
        digest = (photo.file_hash or "").strip()
        if not digest:
            skipped_no_hash += 1
            continue
        by_hash[digest].append(photo)

    groups: list[DuplicateGroup] = []
    for digest, members in by_hash.items():
        if len(members) < 2:
            continue
        keeper = choose_keeper(members)
        duplicates = tuple(
            sorted(
                (photo for photo in members if photo is not keeper),
                key=lambda photo: str(photo.original_path).lower(),
            )
        )
        # If identity failed (shouldn't), fall back to id comparison.
        if not duplicates:
            duplicates = tuple(
                photo for photo in members if photo.id != keeper.id
            )
        if not duplicates:
            continue
        groups.append(
            DuplicateGroup(
                file_hash=digest,
                keeper=keeper,
                duplicates=duplicates,
            )
        )

    groups.sort(
        key=lambda group: (
            -len(group.duplicates),
            str(group.keeper.original_path).lower(),
        )
    )
    return DuplicateScanResult(
        groups=tuple(groups),
        skipped_no_hash=skipped_no_hash,
    )


def photos_to_exclude(result: DuplicateScanResult) -> list[PhotoRecord]:
    """Flatten removable duplicates from a scan result."""
    removable: list[PhotoRecord] = []
    for group in result.groups:
        removable.extend(group.duplicates)
    return removable
