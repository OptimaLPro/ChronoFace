"""Tests for Phase 2 metadata helpers."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import piexif
from PIL import Image

from src.domain.models import DateReliability
from src.metadata.age_from_dob import (
    age_from_dob_and_capture,
    age_years_at,
    clamp_age_to_dob,
    max_age_years,
)
from src.metadata.exif_reader import read_photo_metadata
from src.metadata.filename_parser import guess_year_from_name
from src.metadata.image_discovery import discover_images


def _write_jpeg_with_exif(path: Path, when: datetime) -> None:
    image = Image.new("RGB", (32, 32), color=(20, 40, 60))
    exif_dict = {
        "0th": {piexif.ImageIFD.DateTime: when.strftime("%Y:%m:%d %H:%M:%S").encode()},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: when.strftime("%Y:%m:%d %H:%M:%S").encode()
        },
        "1st": {},
        "thumbnail": None,
        "GPS": {},
    }
    exif_bytes = piexif.dump(exif_dict)
    image.save(path, format="JPEG", exif=exif_bytes)


def test_discover_images_filters_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.PNG").write_bytes(b"x")
    (tmp_path / "c.txt").write_bytes(b"x")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "d.webp").write_bytes(b"x")
    (nested / "e.bmp").write_bytes(b"x")

    found = discover_images(tmp_path)
    names = {path.name.lower() for path in found}
    assert names == {"a.jpg", "b.png", "d.webp"}


def test_guess_year_from_filename() -> None:
    assert guess_year_from_name(Path("IMG_2018_vacation.jpg")) == 2018
    assert guess_year_from_name(Path("party-2023-05-01.png")) == 2023
    assert guess_year_from_name(Path("no-year.jpg")) is None


def test_read_photo_metadata_prefers_exif(tmp_path: Path) -> None:
    path = tmp_path / "shot.jpg"
    when = datetime(2015, 6, 15, 12, 30, 0)
    _write_jpeg_with_exif(path, when)

    result = read_photo_metadata(path)
    assert result.reliability == DateReliability.RELIABLE_EXIF
    assert result.capture_date is not None
    assert result.capture_date.year == 2015
    assert result.source == "exif_datetime_original"


def test_read_photo_metadata_falls_back_to_filesystem(tmp_path: Path) -> None:
    path = tmp_path / "plain.png"
    Image.new("RGB", (16, 16), color=(1, 2, 3)).save(path)

    result = read_photo_metadata(path)
    assert result.reliability == DateReliability.WEAK_FILESYSTEM
    assert result.capture_date is not None


def test_age_from_dob() -> None:
    dob = date(2010, 1, 1)
    captured = datetime(2020, 1, 1)
    age = age_from_dob_and_capture(dob, captured)
    assert age is not None
    assert 9.9 < age < 10.1
    assert age_years_at(dob, date(2010, 7, 1)) > 0


def test_clamp_age_to_dob_ceiling() -> None:
    dob = date(2009, 10, 30)
    ceiling = max_age_years(dob, as_of=date(2026, 7, 24))
    assert ceiling is not None
    assert 16.0 < ceiling < 17.0

    clamped, was_clamped = clamp_age_to_dob(76.0, dob, as_of=date(2026, 7, 24))
    assert was_clamped
    assert clamped == round(ceiling, 2)

    ok, was_clamped = clamp_age_to_dob(12.0, dob, as_of=date(2026, 7, 24))
    assert not was_clamped
    assert ok == 12.0

    untouched, was_clamped = clamp_age_to_dob(76.0, None)
    assert not was_clamped
    assert untouched == 76.0
