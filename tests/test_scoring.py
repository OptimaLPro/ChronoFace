"""Tests for age-group helpers and sort scoring."""

from datetime import date, datetime
from pathlib import Path

from src.domain.models import (
    DateReliability,
    PhotoAnalysis,
    PhotoRecord,
    ReviewStatus,
)
from src.sorting.grouping import age_group_label
from src.sorting.ranking import rank_photo_records, rank_photos
from src.sorting.scoring import calculate_sort_score, decide_sort_for_record


def test_age_group_label_buckets() -> None:
    assert age_group_label(1) == "0-2"
    assert age_group_label(8) == "6-9"
    assert age_group_label(16) == "14-17"
    assert age_group_label(60) == "51+"
    assert age_group_label(None) == "unknown"


def test_calculate_sort_score_prefers_manual_age() -> None:
    photo = PhotoAnalysis(
        path=Path("a.jpg"),
        target_found=True,
        identity_score=0.9,
        estimated_age=20.0,
        capture_date=None,
        face_quality=0.8,
        age_confidence=0.5,
        overall_confidence=0.7,
        manual_age=7.0,
        review_status=ReviewStatus.MANUALLY_CORRECTED,
    )
    assert calculate_sort_score(photo) == 7.0


def test_rank_photos_youngest_first() -> None:
    photos = [
        PhotoAnalysis(
            path=Path("older.jpg"),
            target_found=True,
            identity_score=0.9,
            estimated_age=15.0,
            capture_date=None,
            face_quality=0.8,
            age_confidence=0.5,
            overall_confidence=0.7,
        ),
        PhotoAnalysis(
            path=Path("younger.jpg"),
            target_found=True,
            identity_score=0.9,
            estimated_age=5.0,
            capture_date=None,
            face_quality=0.8,
            age_confidence=0.5,
            overall_confidence=0.7,
        ),
    ]
    ranked = rank_photos(photos)
    assert ranked[0].path.name == "younger.jpg"
    assert ranked[1].path.name == "older.jpg"


def test_dob_exif_beats_facial_estimate() -> None:
    photo = PhotoRecord(
        project_id="p",
        original_path=Path("a.jpg"),
        age_from_dob=6.2,
        estimated_age=11.0,
        date_reliability=DateReliability.RELIABLE_EXIF,
        capture_date=datetime(2016, 1, 1),
    )
    decision = decide_sort_for_record(photo, date_of_birth=date(2010, 1, 1))
    assert decision.reason == "dob_plus_exif"
    assert decision.sort_score == 6.2


def test_facial_age_clamped_by_dob_max() -> None:
    """A 16-year-old subject cannot receive a 76y facial estimate."""
    dob = date(2009, 10, 30)
    photo = PhotoRecord(
        project_id="p",
        original_path=Path("wild.jpg"),
        estimated_age=76.0,
        age_confidence=0.7,
    )
    decision = decide_sort_for_record(photo, date_of_birth=dob)
    assert decision.reason == "facial_age_estimate"
    assert decision.effective_age is not None
    assert decision.effective_age < 17.0
    assert decision.age_confidence <= 0.25


def test_impossible_facial_age_prefers_filename_year() -> None:
    dob = date(2009, 10, 30)
    photo = PhotoRecord(
        project_id="p",
        original_path=Path("IMG_2015.jpg"),
        estimated_age=60.0,
        age_confidence=0.7,
        filename_year=2015,
    )
    decision = decide_sort_for_record(photo, date_of_birth=dob)
    assert decision.reason == "dob_plus_filename_year"
    assert decision.effective_age == 6.0


def test_rank_photo_records_orders_by_age() -> None:
    photos = [
        PhotoRecord(
            project_id="p",
            original_path=Path("old.jpg"),
            estimated_age=14.0,
            age_confidence=0.5,
        ),
        PhotoRecord(
            project_id="p",
            original_path=Path("young.jpg"),
            estimated_age=3.0,
            age_confidence=0.5,
        ),
        PhotoRecord(
            project_id="p",
            original_path=Path("unknown.jpg"),
        ),
    ]
    ranked = rank_photo_records(photos)
    assert ranked[0].original_path.name == "young.jpg"
    assert ranked[1].original_path.name == "old.jpg"
    assert ranked[2].original_path.name == "unknown.jpg"
