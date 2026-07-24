"""Tests for numbered export and CSV reporting."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.domain.models import PhotoRecord, ReviewStatus
from src.export.csv_exporter import export_csv_report
from src.export.file_exporter import (
    ExportOptions,
    build_export_filename,
    export_numbered_copies,
    sanitize_filename,
)


def _photo(tmp_path: Path, name: str, *, age: float, target: bool) -> PhotoRecord:
    path = tmp_path / name
    Image.new("RGB", (20, 20), color=(100, 120, 140)).save(path)
    return PhotoRecord(
        project_id="p",
        original_path=path,
        estimated_age=age,
        age_confidence=0.6,
        target_found=target,
        review_status=ReviewStatus.NEEDS_REVIEW if target else ReviewStatus.NO_FACE,
        identity_score=0.8 if target else 0.1,
    )


def test_sanitize_and_filename() -> None:
    assert ":" not in sanitize_filename("bad:name*.jpg")
    photo = PhotoRecord(
        project_id="p",
        original_path=Path("holiday.jpg"),
        estimated_age=7.4,
        target_found=True,
    )
    assert build_export_filename(1, photo, include_age_in_name=True) == (
        "0001_age_07_holiday.jpg"
    )
    assert build_export_filename(2, photo, include_age_in_name=False) == (
        "0002_holiday.jpg"
    )


def test_export_numbered_copies_and_csv(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()

    young = _photo(input_dir, "young.jpg", age=3.0, target=True)
    older = _photo(input_dir, "older.jpg", age=12.0, target=True)
    missing = _photo(input_dir, "noface.jpg", age=9.0, target=False)

    result = export_numbered_copies(
        [young, older, missing],
        ExportOptions(
            output_dir=output_dir,
            include_age_in_name=True,
            export_unresolved_separate=True,
            export_excluded_separate=True,
            write_csv=False,
        ),
    )

    assert result.exported_main == 2
    assert result.exported_excluded == 1
    assert result.output_dir == output_dir
    main_files = sorted(p.name for p in output_dir.glob("*.jpg"))
    assert main_files[0].startswith("0001_age_03_young")
    assert main_files[1].startswith("0002_age_12_older")
    assert (output_dir / "_excluded").is_dir()

    assert young.original_path.is_file()
    assert older.original_path.is_file()

    csv_path = export_csv_report(result.items, output_dir / "export_report.csv")
    text = csv_path.read_text(encoding="utf-8")
    assert "output_order" in text
    assert "young.jpg" in text


def test_export_skips_excluded_photos(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()

    kept = _photo(input_dir, "kept.jpg", age=5.0, target=True)
    removed = _photo(input_dir, "removed.jpg", age=8.0, target=True)
    removed.review_status = ReviewStatus.EXCLUDED

    result = export_numbered_copies(
        [kept, removed],
        ExportOptions(
            output_dir=output_dir,
            include_age_in_name=False,
            export_unresolved_separate=True,
            export_excluded_separate=True,
            write_csv=False,
        ),
    )

    assert result.exported_main == 1
    assert result.exported_excluded == 0
    assert list(output_dir.glob("*.jpg"))
    assert not (output_dir / "_excluded").exists()
    assert removed.original_path.is_file()
