"""EXIF / capture-date reading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import piexif
from PIL import Image, UnidentifiedImageError

from src.domain.models import DateReliability
from src.utils.logging import get_logger

logger = get_logger("metadata.exif_reader")

_EXIF_DATETIME_FORMATS = (
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y:%m:%d %H:%M:%S%z",
)


@dataclass
class MetadataResult:
    """All date-related signals extracted from a photo file."""

    capture_date: Optional[datetime]
    reliability: DateReliability
    source: str
    file_created_at: Optional[datetime] = None
    file_modified_at: Optional[datetime] = None
    exif_datetime_original: Optional[datetime] = None
    exif_create_date: Optional[datetime] = None


def _parse_exif_datetime(raw: object) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="ignore").strip().rstrip("\x00")
    else:
        text = str(raw).strip()
    if not text or text.startswith("0000"):
        return None
    for fmt in _EXIF_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    logger.debug("Unrecognized EXIF datetime value: %r", text)
    return None


def _read_exif_dates(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
    datetime_original: Optional[datetime] = None
    create_date: Optional[datetime] = None

    try:
        exif_dict = piexif.load(str(path))
    except Exception:  # noqa: BLE001 — piexif raises many types on bad data
        # Fall back to Pillow's EXIF parser for formats piexif struggles with.
        try:
            with Image.open(path) as image:
                exif = image.getexif()
                if not exif:
                    return None, None
                # 36867 = DateTimeOriginal, 36868 = DateTimeDigitized, 306 = DateTime
                datetime_original = _parse_exif_datetime(exif.get(36867))
                create_date = _parse_exif_datetime(exif.get(36868) or exif.get(306))
                return datetime_original, create_date
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            logger.debug("No readable EXIF for %s: %s", path.name, exc)
            return None, None

    try:
        exif_ifd = exif_dict.get("Exif") or {}
        zeroth = exif_dict.get("0th") or {}
        datetime_original = _parse_exif_datetime(
            exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
        )
        create_date = _parse_exif_datetime(
            exif_ifd.get(piexif.ExifIFD.DateTimeDigitized)
        ) or _parse_exif_datetime(zeroth.get(piexif.ImageIFD.DateTime))
    except Exception as exc:  # noqa: BLE001
        logger.debug("EXIF parse error for %s: %s", path.name, exc)

    return datetime_original, create_date


def _filesystem_times(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
    try:
        stat = path.stat()
    except OSError as exc:
        logger.warning("Could not stat %s: %s", path, exc)
        return None, None

    modified = datetime.fromtimestamp(stat.st_mtime)
    # On Windows, st_ctime is creation time; on Unix it is inode change time.
    created = datetime.fromtimestamp(stat.st_ctime)
    return created, modified


def read_photo_metadata(path: Path) -> MetadataResult:
    """
    Extract capture-date signals from a photo.

    Priority:
    1. EXIF DateTimeOriginal (reliable)
    2. EXIF Digitized / DateTime (reliable)
    3. Filesystem created/modified times (weak — may be download/copy date)
    4. None
    """
    path = Path(path)
    file_created, file_modified = _filesystem_times(path)
    datetime_original, create_date = _read_exif_dates(path)

    if datetime_original is not None:
        return MetadataResult(
            capture_date=datetime_original,
            reliability=DateReliability.RELIABLE_EXIF,
            source="exif_datetime_original",
            file_created_at=file_created,
            file_modified_at=file_modified,
            exif_datetime_original=datetime_original,
            exif_create_date=create_date,
        )

    if create_date is not None:
        return MetadataResult(
            capture_date=create_date,
            reliability=DateReliability.RELIABLE_EXIF,
            source="exif_create_date",
            file_created_at=file_created,
            file_modified_at=file_modified,
            exif_datetime_original=datetime_original,
            exif_create_date=create_date,
        )

    # Prefer the earlier of created/modified as a weak signal only.
    weak_candidates = [dt for dt in (file_created, file_modified) if dt is not None]
    if weak_candidates:
        weak = min(weak_candidates)
        source = (
            "filesystem_created"
            if file_created is not None and weak == file_created
            else "filesystem_modified"
        )
        return MetadataResult(
            capture_date=weak,
            reliability=DateReliability.WEAK_FILESYSTEM,
            source=source,
            file_created_at=file_created,
            file_modified_at=file_modified,
            exif_datetime_original=datetime_original,
            exif_create_date=create_date,
        )

    return MetadataResult(
        capture_date=None,
        reliability=DateReliability.NONE,
        source="none",
        file_created_at=file_created,
        file_modified_at=file_modified,
        exif_datetime_original=datetime_original,
        exif_create_date=create_date,
    )
